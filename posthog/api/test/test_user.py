from .base import BaseTest

class TestUser(BaseTest):
    TESTS_API = True
    def test_redirect_to_site(self):
        self.team.app_url = 'http://somewebsite.com'
        self.team.save()
        response = self.client.get('/api/user/redirect_to_site/?actionId=1')
        self.assertIn('http://somewebsite.com', response.url)