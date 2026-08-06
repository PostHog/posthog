import uuid
from datetime import timedelta
from importlib import import_module

from posthog.test.base import BaseTest

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.utils import timezone

from dagster import build_op_context
from loginas import settings as la_settings

from posthog.dags.backfill_user_auth_sessions import backfill_user_auth_sessions_op
from posthog.models import User
from posthog.session.backfill import backfill_session_user_ids
from posthog.session.models import Session


class _BackfillTestBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _legacy_session(self, user: User | None = None, impersonated: bool = False, anonymous: bool = False) -> str:
        """A session row as it would look before the swap: authenticated data but no stamped user_id."""
        store = self.engine.SessionStore()
        if not anonymous:
            store[SESSION_KEY] = str((user or self._make_user()).pk)
            store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        if impersonated:
            store[la_settings.USER_SESSION_FLAG] = "signed-original-user-pk"
        store["filler"] = "x"  # ensure an anonymous session still has data to persist
        store.create()
        Session.objects.filter(session_key=store.session_key).update(user_id=None, login_method=None)
        return store.session_key


class TestBackfillSessionUserIds(_BackfillTestBase):
    def test_backfills_user_id_and_metadata(self):
        user = self._make_user()
        key = self._legacy_session(user)

        stats = backfill_session_user_ids(dry_run=False)

        row = Session.objects.get(session_key=key)
        self.assertEqual(row.user_id, user.pk)
        self.assertEqual(row.login_method, "password")
        self.assertEqual(stats.updated, 1)

    def test_skips_anonymous_sessions(self):
        key = self._legacy_session(anonymous=True)

        stats = backfill_session_user_ids(dry_run=False)

        self.assertIsNone(Session.objects.get(session_key=key).user_id)
        self.assertEqual(stats.updated, 0)

    def test_skips_impersonation_sessions(self):
        user = self._make_user()
        key = self._legacy_session(user, impersonated=True)

        backfill_session_user_ids(dry_run=False)

        self.assertIsNone(Session.objects.get(session_key=key).user_id)

    def test_dry_run_writes_nothing_but_reports_count(self):
        user = self._make_user()
        key = self._legacy_session(user)

        stats = backfill_session_user_ids(dry_run=True)

        self.assertIsNone(Session.objects.get(session_key=key).user_id)
        self.assertEqual(stats.updated, 1)

    def test_second_run_is_a_noop(self):
        user = self._make_user()
        key = self._legacy_session(user)

        backfill_session_user_ids(dry_run=False)  # first run attributes the session
        stats = backfill_session_user_ids(dry_run=False)  # already attributed → nothing to do

        self.assertEqual(stats.updated, 0)
        self.assertEqual(Session.objects.get(session_key=key).user_id, user.pk)

    def test_skips_deleted_user(self):
        user = self._make_user()
        key = self._legacy_session(user)
        user.delete()

        backfill_session_user_ids(dry_run=False)

        self.assertIsNone(Session.objects.get(session_key=key).user_id)

    def test_ignores_expired_sessions(self):
        user = self._make_user()
        key = self._legacy_session(user)
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(days=1))

        backfill_session_user_ids(dry_run=False)

        self.assertIsNone(Session.objects.get(session_key=key).user_id)


class TestBackfillUserAuthSessionsOp(_BackfillTestBase):
    def test_op_backfills_when_not_dry_run(self):
        user = self._make_user()
        key = self._legacy_session(user)

        backfill_user_auth_sessions_op(build_op_context(op_config={"dry_run": False}))

        self.assertEqual(Session.objects.get(session_key=key).user_id, user.pk)

    def test_op_defaults_to_dry_run(self):
        user = self._make_user()
        key = self._legacy_session(user)

        backfill_user_auth_sessions_op(build_op_context())

        self.assertIsNone(Session.objects.get(session_key=key).user_id)
