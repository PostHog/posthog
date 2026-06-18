import time
from importlib import import_module
from io import StringIO

from posthog.test.base import BaseTest

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.utils import timezone

from loginas import settings as la_settings

from posthog.constants import AUTH_BACKEND_KEYS
from posthog.models import UserAuthSession


class TestBackfillUserAuthSessions(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _session(self, data: dict) -> str:
        session = self.engine.SessionStore()
        for key, value in data.items():
            session[key] = value
        session.create()
        return session.session_key

    def test_backfills_authenticated_session(self):
        key = self._session({"_auth_user_id": str(self.user.pk)})

        call_command("backfill_user_auth_sessions")

        row = UserAuthSession.objects.get(session_key=key)
        self.assertEqual(row.user, self.user)

    def test_is_idempotent(self):
        self._session({"_auth_user_id": str(self.user.pk)})

        call_command("backfill_user_auth_sessions")
        call_command("backfill_user_auth_sessions")

        self.assertEqual(UserAuthSession.objects.filter(user=self.user).count(), 1)

    def test_reports_only_newly_inserted_rows(self):
        # One session is already indexed; only the not-yet-indexed one should be counted as indexed.
        already_indexed = self._session({"_auth_user_id": str(self.user.pk)})
        UserAuthSession.objects.create(user=self.user, session_key=already_indexed)
        self._session({"_auth_user_id": str(self.user.pk)})  # new, not yet indexed

        out = StringIO()
        call_command("backfill_user_auth_sessions", stdout=out)

        self.assertEqual(UserAuthSession.objects.filter(user=self.user).count(), 2)
        self.assertIn("indexed 1", out.getvalue())

    def test_records_created_at_and_login_method(self):
        backend = next(iter(AUTH_BACKEND_KEYS))
        created = time.time() - 3600
        key = self._session(
            {
                "_auth_user_id": str(self.user.pk),
                BACKEND_SESSION_KEY: backend,
                settings.SESSION_COOKIE_CREATED_AT_KEY: created,
            }
        )

        call_command("backfill_user_auth_sessions")

        row = UserAuthSession.objects.get(session_key=key)
        self.assertEqual(row.login_method, AUTH_BACKEND_KEYS[backend])
        self.assertAlmostEqual(row.created_at.timestamp(), created, delta=2)

    def test_skips_impersonation_sessions(self):
        key = self._session({"_auth_user_id": str(self.user.pk), la_settings.USER_SESSION_FLAG: "signed-pk"})

        call_command("backfill_user_auth_sessions")

        self.assertFalse(UserAuthSession.objects.filter(session_key=key).exists())

    def test_skips_anonymous_sessions(self):
        self._session({"some": "value"})  # no _auth_user_id

        call_command("backfill_user_auth_sessions")

        self.assertEqual(UserAuthSession.objects.count(), 0)

    def test_skips_expired_sessions(self):
        key = self._session({"_auth_user_id": str(self.user.pk)})
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timezone.timedelta(days=1))

        call_command("backfill_user_auth_sessions")

        self.assertFalse(UserAuthSession.objects.filter(session_key=key).exists())

    def test_skips_sessions_for_missing_users(self):
        self._session({"_auth_user_id": "99999999"})  # no such user

        call_command("backfill_user_auth_sessions")

        self.assertEqual(UserAuthSession.objects.count(), 0)

    def test_dry_run_creates_nothing(self):
        self._session({"_auth_user_id": str(self.user.pk)})

        call_command("backfill_user_auth_sessions", "--dry-run")

        self.assertEqual(UserAuthSession.objects.count(), 0)
