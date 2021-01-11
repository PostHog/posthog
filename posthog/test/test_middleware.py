from django.conf import settings
from django.test import Client, TestCase
from rest_framework import status

from posthog.test.base import BaseTest


class TestSignup(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_ip_range(self):
        """
        Also test that capture endpoint is not restrictied by ALLOWED_IP_BLOCKS
        """

        with self.settings(ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25", "128.0.0.1"]):

            # not in list
            response = self.client.get("/", REMOTE_ADDR="10.0.0.1")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"IP is not allowed", response.content)

            response = self.client.get("/batch/", REMOTE_ADDR="10.0.0.1",)

            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST
            )  # Check for a bad request exception because it means the middleware didn't block the request

            # /31 block
            response = self.client.get("/", REMOTE_ADDR="192.168.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="192.168.0.2")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"IP is not allowed", response.content)

            response = self.client.get("/batch/", REMOTE_ADDR="192.168.0.1")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            response = self.client.get("/batch/", REMOTE_ADDR="192.168.0.2")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            # /24 block
            response = self.client.get("/", REMOTE_ADDR="127.0.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="127.0.0.100")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="127.0.0.200")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"IP is not allowed", response.content)

            # precise ip
            response = self.client.get("/", REMOTE_ADDR="128.0.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="128.0.0.2")
            self.assertIn(b"IP is not allowed", response.content)

    def test_trusted_proxies(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"], USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.1",)
                self.assertNotIn(b"IP is not allowed", response.content)

    def test_attempt_spoofing(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"], USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.2",)
                self.assertIn(b"IP is not allowed", response.content)

    def test_trust_all_proxies(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"], USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUST_ALL_PROXIES=True):
                response = self.client.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.1",)
                self.assertNotIn(b"IP is not allowed", response.content)


class TestToolbarCookieMiddleware(BaseTest):
    TESTS_API = True
    TESTS_FORCE_LOGIN = False

    def test_logged_out_client(self):
        response = self.client.get("/")
        self.assertEqual(0, len(response.cookies))

    def test_logged_in_client(self):
        with self.settings(TOOLBAR_COOKIE_NAME="phtoolbar", TOOLBAR_COOKIE_SECURE=False):
            self.client.force_login(self.user)

            response = self.client.get("/")
            toolbar_cookie = response.cookies[settings.TOOLBAR_COOKIE_NAME]

            self.assertEqual(toolbar_cookie.key, settings.TOOLBAR_COOKIE_NAME)
            self.assertEqual(toolbar_cookie.value, "yes")
            self.assertEqual(toolbar_cookie["path"], "/")
            self.assertEqual(toolbar_cookie["samesite"], "None")
            self.assertEqual(toolbar_cookie["httponly"], True)
            self.assertEqual(toolbar_cookie["domain"], "")
            self.assertEqual(toolbar_cookie["comment"], "")
            self.assertEqual(toolbar_cookie["secure"], "")
            self.assertEqual(toolbar_cookie["max-age"], 31536000)

    def test_logged_in_client_secure(self):
        with self.settings(TOOLBAR_COOKIE_NAME="phtoolbar", TOOLBAR_COOKIE_SECURE=True):
            self.client.force_login(self.user)

            response = self.client.get("/")
            toolbar_cookie = response.cookies[settings.TOOLBAR_COOKIE_NAME]

            self.assertEqual(toolbar_cookie.key, "phtoolbar")
            self.assertEqual(toolbar_cookie.value, "yes")
            self.assertEqual(toolbar_cookie["path"], "/")
            self.assertEqual(toolbar_cookie["samesite"], "None")
            self.assertEqual(toolbar_cookie["httponly"], True)
            self.assertEqual(toolbar_cookie["domain"], "")
            self.assertEqual(toolbar_cookie["comment"], "")
            self.assertEqual(toolbar_cookie["secure"], True)
            self.assertEqual(toolbar_cookie["max-age"], 31536000)

    def test_logout(self):
        with self.settings(TOOLBAR_COOKIE_NAME="phtoolbar"):
            self.client.force_login(self.user)

            response = self.client.get("/")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].key, "phtoolbar")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].value, "yes")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME]["max-age"], 31536000)

            response = self.client.get("/logout")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].key, "phtoolbar")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].value, "")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME]["max-age"], 0)
