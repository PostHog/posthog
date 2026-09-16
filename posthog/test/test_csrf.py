from posthog.test.base import APIBaseTest

from django.test import RequestFactory

from parameterized import parameterized
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIClient


class TestCSRFProtection(APIBaseTest):
    """`/api/` writes are checked by `SessionAuthentication.enforce_csrf` (see `posthog.csrf`)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def annotation_write(self, **headers):
        return self.client.post(f"/api/projects/{self.team.pk}/annotations/", {"content": "hello"}, **headers)

    def test_write_succeeds_without_a_csrf_cookie_or_token(self):
        # The reported dead end: a tab whose CSRF cookie is gone kept a working session and lost
        # every write. `Sec-Fetch-Site` comes from the browser, so nothing has to survive in the tab.
        response = self.annotation_write(HTTP_SEC_FETCH_SITE="same-origin")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_write_succeeds_when_the_csrf_cookie_no_longer_matches_the_sent_token(self):
        self.client.cookies["posthog_csrftoken"] = "a-cookie-from-an-older-session"

        response = self.annotation_write(HTTP_SEC_FETCH_SITE="same-origin", HTTP_X_CSRFTOKEN="a-stale-token")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_write_from_an_untrusted_origin_succeeds_when_the_browser_calls_it_same_origin(self):
        # A self-hosted instance served on a host its `CSRF_TRUSTED_ORIGINS` does not name. The
        # browser has already established the request is same-origin, so the setting is not needed.
        response = self.annotation_write(HTTP_SEC_FETCH_SITE="same-origin", HTTP_ORIGIN="https://analytics.example.com")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand(["cross-site", "same-site"])
    def test_write_is_rejected_when_the_browser_calls_it_cross_origin(self, sec_fetch_site):
        response = self.annotation_write(HTTP_SEC_FETCH_SITE=sec_fetch_site, HTTP_ORIGIN="https://attacker.example.com")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("CSRF Failed", response.json()["detail"])

    def test_write_is_rejected_on_an_untrusted_origin_without_fetch_metadata(self):
        # An older browser sends no `Sec-Fetch-Site`, so the `Origin` header is the only signal.
        response = self.annotation_write(HTTP_ORIGIN="https://attacker.example.com")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestRestFrameworkSessionAuthentication(APIBaseTest):
    """A dozen product viewsets declare REST Framework's own `SessionAuthentication` rather than
    the subclass in `posthog.auth`, and it runs the CSRF check itself."""

    def enforce_csrf(self, **headers):
        request = Request(RequestFactory().post("/api/projects/@current/annotations/", **headers))
        return SessionAuthentication().enforce_csrf(request)

    def test_write_is_accepted_without_a_csrf_cookie_or_token(self):
        self.assertIsNone(self.enforce_csrf(HTTP_SEC_FETCH_SITE="same-origin"))

    def test_write_is_rejected_when_the_browser_calls_it_cross_origin(self):
        with self.assertRaises(PermissionDenied):
            self.enforce_csrf(HTTP_SEC_FETCH_SITE="cross-site", HTTP_ORIGIN="https://attacker.example.com")
