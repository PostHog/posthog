from posthog.test.base import BaseTest

from django.test import RequestFactory

from posthog.middleware_guest import GuestDeflectionMiddleware


class TestGuestDeflectionMiddleware(BaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _middleware(self, response=None):
        response = response or (lambda request: type("R", (), {"status_code": 200})())
        return GuestDeflectionMiddleware(response)

    def test_non_guest_user_passes_through(self):
        mw = self._middleware()
        request = self.factory.get("/api/projects/@current/feature_flags/")
        request.user = self.user
        response = mw(request)
        self.assertEqual(response.status_code, 200)

    def test_anonymous_user_passes_through(self):
        from django.contrib.auth.models import AnonymousUser

        mw = self._middleware()
        request = self.factory.get("/api/login/")
        request.user = AnonymousUser()
        response = mw(request)
        self.assertEqual(response.status_code, 200)
