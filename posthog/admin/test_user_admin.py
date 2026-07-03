import uuid
from importlib import import_module

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import SESSION_KEY
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse

from posthog.admin.admins.user_admin import UserAdmin
from posthog.models import User
from posthog.session.models import Session


class TestUserAdminSessions(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)
        self.admin = UserAdmin(User, AdminSite())

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _login_session(self, user: User) -> str:
        store = self.engine.SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store.create()
        return store.session_key

    def test_delete_user_sessions_revokes_all_of_the_users_sessions(self):
        user = self._make_user()
        other_user = self._make_user()
        keys = [self._login_session(user), self._login_session(user)]
        other_key = self._login_session(other_user)

        count = self.admin.delete_user_sessions(user)

        self.assertEqual(count, 2)
        self.assertFalse(Session.objects.filter(session_key__in=keys).exists())
        self.assertTrue(Session.objects.filter(session_key=other_key).exists())  # other user untouched


class TestUserAdminPasswordReset(BaseTest):
    def setUp(self):
        super().setUp()
        self.admin = UserAdmin(User, AdminSite())

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _request(self, method: str = "post", data: dict | None = None):
        request = getattr(RequestFactory(), method)("/", data or {})
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_user_change_password_redirects_instead_of_erroring(self):
        # Guards the reported 500: change_password_form is None, so without this override Django's
        # inherited password view crashes with TypeError instead of redirecting to the change page.
        user = self._make_user()

        response = self.admin.user_change_password(self._request(method="get"), user.pk)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:posthog_user_change", args=[user.pk]))

    @patch("posthog.admin.admins.user_admin.send_password_reset")
    def test_send_password_reset_sets_timestamp_and_dispatches_email(self, mock_send_password_reset):
        user = self._make_user()
        self.assertIsNone(user.requested_password_reset_at)

        response = self.admin.change_view(self._request(data={"send_password_reset": "1"}), str(user.pk))

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertIsNotNone(user.requested_password_reset_at)
        mock_send_password_reset.delay.assert_called_once()
        user_pk, token = mock_send_password_reset.delay.call_args.args[:2]
        self.assertEqual(user_pk, user.pk)
        # A usable reset token must be forwarded — an empty/None token would email a dead link.
        self.assertIsInstance(token, str)
        self.assertTrue(token)
