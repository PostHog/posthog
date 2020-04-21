from django.test import TestCase, Client

class TestSignup(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
     
    def test_ip_range(self):
        with self.settings(ALLOWED_IP_BLOCKS='192.168.0.0/31,127.0.0.0/31,128.0.0.1'):
            response = self.client.get('/', REMOTE_ADDR='10.0.0.1')
            self.assertIn(b'IP is not allowed', response.content)

            response = self.client.get('/', REMOTE_ADDR='192.168.0.1')
            self.assertNotIn(b'IP is not allowed', response.content)

            response = self.client.get('/batch/', REMOTE_ADDR='10.0.0.1')
            self.assertEqual(b'1', response.content)

            response = self.client.get('/', REMOTE_ADDR='127.0.0.1')
            self.assertNotIn(b'IP is not allowed', response.content)

            response = self.client.get('/', REMOTE_ADDR='128.0.0.1')
            self.assertNotIn(b'IP is not allowed', response.content)