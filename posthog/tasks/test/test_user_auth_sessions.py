from importlib import import_module

from posthog.test.base import BaseTest

from django.conf import settings
from django.contrib.sessions.models import Session
from django.utils import timezone

from posthog.models import UserAuthSession
from posthog.tasks.user_auth_sessions import cleanup_user_auth_sessions


class TestCleanupUserAuthSessions(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _live_session(self) -> str:
        session = self.engine.SessionStore()
        session["_auth_user_id"] = str(self.user.pk)
        session.create()
        return session.session_key

    def test_keeps_rows_with_live_session(self):
        key = self._live_session()
        UserAuthSession.objects.create(user=self.user, session_key=key)

        cleanup_user_auth_sessions()

        self.assertTrue(UserAuthSession.objects.filter(session_key=key).exists())

    def test_deletes_rows_without_backing_session(self):
        UserAuthSession.objects.create(user=self.user, session_key="this-key-has-no-session")

        deleted = cleanup_user_auth_sessions()

        self.assertFalse(UserAuthSession.objects.filter(session_key="this-key-has-no-session").exists())
        self.assertGreaterEqual(deleted, 1)

    def test_deletes_rows_for_expired_sessions(self):
        key = self._live_session()
        UserAuthSession.objects.create(user=self.user, session_key=key)
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timezone.timedelta(days=1))

        cleanup_user_auth_sessions()

        self.assertFalse(UserAuthSession.objects.filter(session_key=key).exists())
