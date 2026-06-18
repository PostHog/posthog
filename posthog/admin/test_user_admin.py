from importlib import import_module

from posthog.test.base import BaseTest

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.sessions.models import Session

from posthog.admin.admins.user_admin import UserAdmin
from posthog.models import User, UserAuthSession


class TestUserAdminSessions(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)
        self.admin = UserAdmin(User, AdminSite())

    def _session(self, user: User) -> str:
        session = self.engine.SessionStore()
        session["_auth_user_id"] = str(user.pk)
        session.create()
        UserAuthSession.objects.create(user=user, session_key=session.session_key)
        return session.session_key

    def test_delete_user_sessions_revokes_all_indexed_sessions(self):
        first = self._session(self.user)
        second = self._session(self.user)

        revoked = self.admin.delete_user_sessions(self.user)

        self.assertEqual(revoked, 2)
        self.assertEqual(UserAuthSession.objects.filter(user=self.user).count(), 0)
        self.assertFalse(Session.objects.filter(session_key__in=[first, second]).exists())

    def test_delete_user_sessions_does_not_affect_other_users(self):
        self._session(self.user)
        other_user = User.objects.create(email="other-admin@example.com", distinct_id="other-admin")
        other_key = self._session(other_user)

        self.admin.delete_user_sessions(self.user)

        self.assertTrue(UserAuthSession.objects.filter(session_key=other_key).exists())
        self.assertTrue(Session.objects.filter(session_key=other_key).exists())
