from .base import BaseTest

from posthog.models import Person, FeatureFlag
from django.conf import settings
import base64
import json

class TestDecide(BaseTest):
    TESTS_API = True

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode('utf-8')).decode('utf-8')

    def test_user_on_own_site(self):
        self.team.app_urls = ['https://example.com/maybesubdomain']
        self.team.save()
        response = self.client.get('/decide/', HTTP_ORIGIN='https://example.com').json()
        self.assertEqual(response['isAuthenticated'], True)
        self.assertEqual(response['editorParams']['toolbarVersion'], settings.TOOLBAR_VERSION)

    def test_user_on_evil_site(self):
        self.team.app_urls = ['https://example.com']
        self.team.save()
        response = self.client.get('/decide/', HTTP_ORIGIN='https://evilsite.com').json()
        self.assertEqual(response['isAuthenticated'], False)
        self.assertIsNone(response['editorParams'].get('toolbarVersion', None))

    def test_user_on_local_host(self):
        self.team.app_urls = ['https://example.com']
        self.team.save()
        response = self.client.get('/decide/', HTTP_ORIGIN='http://127.0.0.1:8000').json()
        self.assertEqual(response['isAuthenticated'], True)
        self.assertEqual(response['editorParams']['toolbarVersion'], settings.TOOLBAR_VERSION)

    def test_feature_flags(self):
        self.team.app_urls = ['https://example.com']
        self.team.save()
        Person.objects.create(team=self.team, distinct_ids=['example_id'])
        FeatureFlag.objects.create(team=self.team, rollout_percentage=50, name='Beta feature', key='beta-feature', created_by=self.user)
        response = self.client.post('/decide/', {'data': self._dict_to_b64({
            'token': self.team.api_token,
            'distinct_id': 'example_id'
        })}, HTTP_ORIGIN='http://127.0.0.1:8000').json()
        self.assertEqual(response['featureFlags'][0], 'beta-feature')

        response = self.client.post('/decide/', {'data': self._dict_to_b64({
            'token': self.team.api_token,
            'distinct_id': 'another_id'
        })}, HTTP_ORIGIN='http://127.0.0.1:8000').json()
        self.assertEqual(len(response['featureFlags']), 0)