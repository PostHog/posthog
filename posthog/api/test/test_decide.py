from .base import BaseTest

from django.conf import settings

class TestDecide(BaseTest):
    TESTS_API = True

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
