import uuid
from datetime import timedelta
from importlib import import_module

from posthog.test.base import BaseTest

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.core.cache import cache
from django.test import RequestFactory
from django.utils import timezone

from loginas import settings as la_settings

from posthog.models import User
from posthog.session.activity import (
    list_user_sessions,
    revoke_other_sessions,
    revoke_other_sessions_for_request,
    revoke_user_auth_session,
    session_public_id,
    sync_current_session_metadata,
)
from posthog.session.models import Session


class TestSessionActivity(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)
        cache.clear()

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _login_session(self, user: User) -> str:
        store = self.engine.SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        store.create()
        return store.session_key

    def _request(self, user: User, session_key: str):
        request = RequestFactory().get("/")
        request.user = user
        request.session = self.engine.SessionStore(session_key=session_key)
        return request

    def test_public_id_is_stable_and_opaque(self):
        key = "some-session-key"
        self.assertEqual(session_public_id(key), session_public_id(key))
        self.assertNotEqual(session_public_id(key), session_public_id("other-key"))
        self.assertNotIn(key, str(session_public_id(key)))

    def test_list_returns_only_the_users_live_sessions(self):
        user = self._make_user()
        other_user = self._make_user()
        key = self._login_session(user)
        self._login_session(other_user)

        sessions = list_user_sessions(user)

        self.assertEqual([s.session_key for s in sessions], [key])

    def test_list_excludes_expired_sessions(self):
        user = self._make_user()
        key = self._login_session(user)
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(days=1))

        self.assertEqual(list_user_sessions(user), [])

    def test_list_sorts_null_last_activity_last(self):
        # A backfilled session (never refreshed since the swap) has NULL last_activity and must sort
        # below sessions with real activity, not above them.
        user = self._make_user()
        active = self._login_session(user)
        idle = self._login_session(user)
        Session.objects.filter(session_key=idle).update(last_activity=None)
        Session.objects.filter(session_key=active).update(last_activity=timezone.now())

        ordered = [s.session_key for s in list_user_sessions(user)]

        self.assertLess(ordered.index(active), ordered.index(idle))

    def test_revoke_other_sessions_keeps_current(self):
        user = self._make_user()
        current = self._login_session(user)
        other = self._login_session(user)

        count = revoke_other_sessions(user, keep_session_key=current)

        self.assertEqual(count, 1)
        self.assertTrue(Session.objects.filter(session_key=current).exists())
        self.assertFalse(Session.objects.filter(session_key=other).exists())

    def test_revoke_other_sessions_does_not_touch_other_users(self):
        user = self._make_user()
        other_user = self._make_user()
        current = self._login_session(user)
        victim = self._login_session(other_user)

        revoke_other_sessions(user, keep_session_key=current)

        self.assertTrue(Session.objects.filter(session_key=victim).exists())

    def test_revoke_user_auth_session_deletes_by_public_id(self):
        user = self._make_user()
        key = self._login_session(user)

        self.assertTrue(revoke_user_auth_session(user, str(session_public_id(key))))
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_revoke_user_auth_session_will_not_revoke_another_users_session(self):
        user = self._make_user()
        other_user = self._make_user()
        victim_key = self._login_session(other_user)

        self.assertFalse(revoke_user_auth_session(user, str(session_public_id(victim_key))))
        self.assertTrue(Session.objects.filter(session_key=victim_key).exists())

    def test_revoke_user_auth_session_returns_false_for_invalid_id(self):
        user = self._make_user()
        self.assertFalse(revoke_user_auth_session(user, "not-a-uuid"))
        self.assertFalse(revoke_user_auth_session(user, str(uuid.uuid4())))

    def test_sync_metadata_populates_current_session(self):
        user = self._make_user()
        key = self._login_session(user)
        request = self._request(user, key)

        with self.captureOnCommitCallbacks(execute=True):
            sync_current_session_metadata(request, force=True)

        row = Session.objects.get(session_key=key)
        self.assertIsNotNone(row.last_activity)
        self.assertEqual(row.login_method, "password")

    def test_sync_writes_display_metadata_not_security_baseline(self):
        # The metadata sync owns display fields only; the risk baseline columns are owned by
        # evaluate_session_risk and must stay untouched here (so a suspicious request can't move them).
        user = self._make_user()
        key = self._login_session(user)
        request = self._request(user, key)
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0"

        with self.captureOnCommitCallbacks(execute=True):
            sync_current_session_metadata(request, force=True)

        row = Session.objects.get(session_key=key)
        self.assertIsNotNone(row.last_activity)  # display metadata written
        self.assertIsNone(row.latitude)  # security baseline left alone
        self.assertIsNone(row.country_code)
        self.assertIsNone(row.ua_signature)
        self.assertIsNone(row.baseline_at)

    def test_sync_metadata_is_throttled(self):
        user = self._make_user()
        key = self._login_session(user)
        request = self._request(user, key)

        with self.captureOnCommitCallbacks(execute=True):
            sync_current_session_metadata(request)  # first write sets the throttle cache key
        marker = timezone.now() - timedelta(hours=1)
        Session.objects.filter(session_key=key).update(last_activity=marker)

        sync_current_session_metadata(request)  # throttled — must not overwrite

        self.assertEqual(Session.objects.get(session_key=key).last_activity, marker)

    def test_sync_metadata_skips_impersonation(self):
        user = self._make_user()
        key = self._login_session(user)
        request = self._request(user, key)
        request.session[la_settings.USER_SESSION_FLAG] = "signed-original-user-pk"

        sync_current_session_metadata(request, force=True)

        self.assertIsNone(Session.objects.get(session_key=key).short_user_agent)

    def test_sync_metadata_is_deferred_to_commit(self):
        # The write is deferred to transaction.on_commit so it never adds a query inside the caller's
        # transaction (which would break assertNumQueries across the suite) or run against a
        # transaction already broken by a handled IntegrityError.
        user = self._make_user()
        key = self._login_session(user)
        request = self._request(user, key)

        request.session.get(BACKEND_SESSION_KEY)  # warm the session cache (auth middleware loads it first)

        # The write adds no query to the caller's transaction — it's deferred to on_commit. Otherwise
        # every assertNumQueries assertion in the suite sees +1, and a transaction already broken by a
        # handled IntegrityError raises when the write runs.
        with self.assertNumQueries(0):
            sync_current_session_metadata(request, force=True)

    def test_user_deletion_purges_their_sessions(self):
        # user_id is a plain BigIntegerField (no FK cascade), so a deleted user's rows — and their
        # ip / location / user-agent — would otherwise linger until the session expires.
        user = self._make_user()
        key = self._login_session(user)
        self.assertTrue(Session.objects.filter(session_key=key).exists())

        user.delete()

        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_revoke_other_sessions_for_request_keeps_current(self):
        user = self._make_user()
        current = self._login_session(user)
        other = self._login_session(user)

        revoked = revoke_other_sessions_for_request(self._request(user, current), user)

        self.assertEqual(revoked, 1)
        self.assertTrue(Session.objects.filter(session_key=current).exists())
        self.assertFalse(Session.objects.filter(session_key=other).exists())

    def test_revoke_other_sessions_for_request_noop_when_impersonated(self):
        user = self._make_user()
        self._login_session(user)
        self._login_session(user)
        impersonated = self.engine.SessionStore()
        impersonated[la_settings.USER_SESSION_FLAG] = "signed-original-user-pk"
        impersonated.create()

        revoked = revoke_other_sessions_for_request(self._request(user, impersonated.session_key), user)

        self.assertEqual(revoked, 0)
        self.assertEqual(Session.objects.filter(user_id=user.pk).count(), 2)

    def test_deactivating_user_revokes_their_sessions(self):
        user = self._make_user()
        key = self._login_session(user)
        other_user = self._make_user()
        other_key = self._login_session(other_user)

        user.is_active = False
        user.save()

        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertTrue(Session.objects.filter(session_key=other_key).exists())  # other users untouched
