import json
import urllib.parse

import requests
from flask_login import current_user

from extensions.ext_database import db
from models.source import DataSourceBinding


class OAuthDataSource:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self):
        raise NotImplementedError()

    def get_access_token(self, code: str):
        raise NotImplementedError()


class NotionOAuth(OAuthDataSource):
    _AUTH_URL = 'https://api.notion.com/v1/oauth/authorize'
    _TOKEN_URL = 'https://api.notion.com/v1/oauth/token'
    _NOTION_PAGE_SEARCH = "https://api.notion.com/v1/search"

    def get_authorization_url(self):
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'owner': 'user'
        }
        return f"{self._AUTH_URL}?{urllib.parse.urlencode(params)}"

    def get_access_token(self, code: str):
        data = {
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri
        }
        headers = {'Accept': 'application/json'}
        auth = (self.client_id, self.client_secret)
        response = requests.post(self._TOKEN_URL, data=data, auth=auth, headers=headers)

        response_json = response.json()
        access_token = response_json.get('access_token')
        if not access_token:
            raise ValueError(f"Error in Notion OAuth: {response_json}")
        workspace_name = response_json.get('workspace_name')
        workspace_icon = response_json.get('workspace_icon')
        workspace_id = response_json.get('workspace_id')
        # get all authorized pages
        pages = self.get_authorized_pages(access_token)
        source_info = {
            'workspace_name': workspace_name,
            'workspace_icon': workspace_icon,
            'workspace_id': workspace_id,
            'pages': pages,
            'total': len(pages)
        }
        # save data source binding
        data_source_binding = DataSourceBinding.query.filter(
            db.and_(
                DataSourceBinding.tenant_id == current_user.current_tenant_id,
                DataSourceBinding.provider == 'notion',
                DataSourceBinding.access_token == access_token
            )
        ).first()
        if data_source_binding:
            data_source_binding.source_info = source_info
            data_source_binding.disabled = False
            db.session.add(data_source_binding)
            db.session.commit()
        else:
            new_data_source_binding = DataSourceBinding(
                tenant_id=current_user.current_tenant_id,
                access_token=access_token,
                source_info=source_info,
                provider='notion'
            )
            db.session.add(new_data_source_binding)
            db.session.commit()

    def sync_data_source(self, binding_id: str):
        # save data source binding
        data_source_binding = DataSourceBinding.query.filter(
            db.and_(
                DataSourceBinding.tenant_id == current_user.current_tenant_id,
                DataSourceBinding.provider == 'notion',
                DataSourceBinding.id == binding_id,
                DataSourceBinding.disabled == False
            )
        ).first()
        if data_source_binding:
            # get all authorized pages
            pages = self.get_authorized_pages(data_source_binding.access_token)
            source_info = data_source_binding.source_info
            source_info['pages'] = pages
            source_info['total'] = len(pages)
            data_source_binding.source_info = source_info
            data_source_binding.disabled = False
            db.session.add(data_source_binding)
            db.session.commit()
        else:
            raise ValueError('Data source binding not found')

    def get_authorized_pages(self, access_token: str):
        pages = []
        page_results = self.notion_page_search(access_token)
        database_results = self.notion_database_search(access_token)
        # get page detail
        for page_result in page_results:
            page_id = page_result['id']
            if 'Name' in page_result['properties']:
                if len(page_result['properties']['Name']['title']) > 0:
                    page_name = page_result['properties']['Name']['title'][0]['plain_text']
                else:
                    page_name = 'Untitled'
            elif 'title' in page_result['properties']:
                if len(page_result['properties']['title']['title']) > 0:
                    page_name = page_result['properties']['title']['title'][0]['plain_text']
                else:
                    page_name = 'Untitled'
            else:
                page_name = 'Untitled'
            page_icon = page_result['icon']
            if page_icon:
                icon_type = page_icon['type']
                icon = page_icon[icon_type]
            else:
                icon = None
            parent = page_result['parent']
            parent_type = parent['type']
            if parent_type == 'workspace':
                parent_id = 'root'
            else:
                parent_id = parent[parent_type]
            page = {
                'page_id': page_id,
                'page_name': page_name,
                'page_icon': icon,
                'parent_id': parent_id,
                'type': 'page'
            }
            pages.append(page)
            # get database detail
            for database_result in database_results:
                page_id = database_result['id']
                if len(database_result['title']) > 0:
                    page_name = database_result['title'][0]['plain_text']
                else:
                    page_name = 'Untitled'
                page_icon = database_result['icon']
                parent = database_result['parent']
                parent_type = parent['type']
                if parent_type == 'workspace':
                    parent_id = 'root'
                else:
                    parent_id = parent[parent_type]
                page = {
                    'page_id': page_id,
                    'page_name': page_name,
                    'page_icon': page_icon,
                    'parent_id': parent_id,
                    'type': 'database'
                }
                pages.append(page)
        return pages

    def notion_page_search(self, access_token: str):
        data = {
            'filter': {
                "value": "page",
                "property": "object"
            }
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {access_token}",
            'Notion-Version': '2022-06-28',
        }
        response = requests.post(url=self._NOTION_PAGE_SEARCH, json=data, headers=headers)
        response_json = response.json()
        results = response_json['results']
        return results

    def notion_database_search(self, access_token: str):
        data = {
            'filter': {
                "value": "database",
                "property": "object"
            }
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {access_token}",
            'Notion-Version': '2022-06-28',
        }
        response = requests.post(url=self._NOTION_PAGE_SEARCH, json=data, headers=headers)
        response_json = response.json()
        results = response_json['results']
        return results
