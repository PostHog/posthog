from posthog.test.base import BaseTest

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from parameterized import parameterized

from posthog.middleware_guest import GuestDeflectionMiddleware
from posthog.models import OrganizationMembership, User


class TestGuestDeflectionMiddleware(BaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _middleware(self, response=None):
        response = response or (lambda request: type("R", (), {"status_code": 200})())
        return GuestDeflectionMiddleware(response)

    def _make_guest_user(self, email: str = "guest@posthog.com") -> User:
        user = User.objects.create_user(email=email, password="x", first_name="Guest")
        OrganizationMembership.objects.create(organization=self.organization, user=user, is_guest=True)
        return user

    def test_non_guest_user_passes_through(self):
        mw = self._middleware()
        request = self.factory.get("/api/projects/@current/feature_flags/")
        request.user = self.user
        response = mw(request)
        self.assertEqual(response.status_code, 200)

    def test_anonymous_user_passes_through(self):
        mw = self._middleware()
        request = self.factory.get("/api/login/")
        request.user = AnonymousUser()
        response = mw(request)
        self.assertEqual(response.status_code, 200)

    @parameterized.expand(
        [
            ("me_get", "GET", "/api/users/@me/", 200),
            ("me_password", "POST", "/api/users/@me/password/", 200),
            ("login_get", "GET", "/login/", 200),
            ("logout", "POST", "/api/logout/", 200),
            ("preflight", "GET", "/_preflight/", 200),
            ("org_current", "GET", "/api/organizations/@current/", 200),
            ("project_current", "GET", "/api/projects/@current/", 200),
            ("environment_current", "GET", "/api/environments/@current/", 200),
            ("data_warehouse", "GET", "/api/projects/1/data_warehouse/", 404),
            ("logs", "GET", "/api/projects/1/logs/", 404),
            ("error_tracking", "GET", "/api/projects/1/error_tracking/", 404),
            ("feature_flags", "GET", "/api/projects/1/feature_flags/", 404),
            ("experiments", "GET", "/api/projects/1/experiments/", 404),
            ("cohorts", "GET", "/api/projects/1/cohorts/", 404),
            ("personal_api_keys", "GET", "/api/personal_api_keys/", 404),
        ]
    )
    def test_guest_path_allowlist(self, _name, method, path, expected_status):
        mw = self._middleware()
        guest = self._make_guest_user(email=f"{_name}@posthog.com")
        request = getattr(self.factory, method.lower())(path)
        request.user = guest
        response = mw(request)
        self.assertEqual(response.status_code, expected_status, f"{method} {path}")

    def test_guest_non_api_path_redirects_to_guest_landing(self):
        mw = self._middleware()
        guest = self._make_guest_user()
        request = self.factory.get("/project/1/data-warehouse")
        request.user = guest
        response = mw(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/guest")
