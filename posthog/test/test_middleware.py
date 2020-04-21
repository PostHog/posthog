from django.test import TestCase, Client

class TestSignup(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
     
    def test_signup_new_team(self):
        with self.settings(ALLOWED_IP_BLOCKS='127\.0\.0\.1'):
            response = self.client.get('/', REMOTE_ADDR='127.0.0.1')
            self.assertNotIn(b'IP is not allowed', response.content)

            response = self.client.get('/', REMOTE_ADDR='127.0.0.2')
            self.assertIn(b'IP is not allowed', response.content)

            response = self.client.get('/batch/', REMOTE_ADDR='127.0.0.2')
            self.assertEqual(b'1', response.content)

        response = self.client.get('/', REMOTE_ADDR='127.0.0.1')
        self.assertNotIn(b'IP is not allowed', response.content)