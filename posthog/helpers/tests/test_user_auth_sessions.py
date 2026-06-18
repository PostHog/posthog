import time
import uuid
from importlib import import_module

from posthog.test.base import BaseTest

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.sessions.models import Session
from django.test import RequestFactory

from loginas import settings as la_settings

from posthog.constants import AUTH_BACKEND_KEYS
from posthog.helpers.user_auth_sessions import (
    AUTH_SESSION_SYNC_INTERVAL_SECONDS,
    AUTH_SESSION_SYNCED_AT_KEY,
    delete_current_auth_session,
    revoke_other_sessions,
    revoke_user_auth_session,
    sync_user_auth_session,
)
from posthog.models import User, UserAuthSession


class TestSyncUserAuthSession(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _session(self, user: User, backend: str = "django.contrib.auth.backends.ModelBackend"):
        session = self.engine.SessionStore()
        session[BACKEND_SESSION_KEY] = backend
        session["_auth_user_id"] = str(user.pk)
        session.create()
        return session

    def _request(self, user: User, session):
        request = RequestFactory().get("/")
        request.user = user
        request.session = session
        return request

    def test_creates_row_for_authenticated_session(self):
        user = self._make_user()
        session = self._session(user)
        request = self._request(user, session)

        sync_user_auth_session(request)

        row = UserAuthSession.objects.get(session_key=session.session_key)
        self.assertEqual(row.user, user)
        self.assertIsNotNone(row.last_activity)

    def test_records_login_method_from_backend(self):
        user = self._make_user()
        backend = next(iter(AUTH_BACKEND_KEYS))
        session = self._session(user, backend=backend)
        request = self._request(user, session)

        sync_user_auth_session(request)

        row = UserAuthSession.objects.get(session_key=session.session_key)
        self.assertEqual(row.login_method, AUTH_BACKEND_KEYS[backend])

    def test_skips_anonymous_request(self):
        from django.contrib.auth.models import AnonymousUser

        session = self.engine.SessionStore()
        session.create()
        request = self._request(AnonymousUser(), session)

        sync_user_auth_session(request)

        self.assertEqual(UserAuthSession.objects.count(), 0)

    def test_skips_session_without_backend_key(self):
        user = self._make_user()
        session = self.engine.SessionStore()
        session.create()  # no BACKEND_SESSION_KEY
        request = self._request(user, session)

        sync_user_auth_session(request)

        self.assertEqual(UserAuthSession.objects.count(), 0)

    def test_throttles_repeated_calls(self):
        user = self._make_user()
        session = self._session(user)
        request = self._request(user, session)

        sync_user_auth_session(request)
        first = UserAuthSession.objects.get(session_key=session.session_key)
        original_activity = first.last_activity

        # Second call within the throttle window must not write again
        sync_user_auth_session(request)
        first.refresh_from_db()
        self.assertEqual(first.last_activity, original_activity)
        self.assertEqual(UserAuthSession.objects.count(), 1)

    def test_refreshes_after_throttle_window(self):
        user = self._make_user()
        session = self._session(user)
        request = self._request(user, session)

        sync_user_auth_session(request)
        row = UserAuthSession.objects.get(session_key=session.session_key)
        UserAuthSession.objects.filter(pk=row.pk).update(last_activity=row.created_at)
        # Pretend the last sync was long ago
        session[AUTH_SESSION_SYNCED_AT_KEY] = time.time() - AUTH_SESSION_SYNC_INTERVAL_SECONDS - 1

        sync_user_auth_session(request)

        row.refresh_from_db()
        self.assertGreater(row.last_activity, row.created_at)
        self.assertEqual(UserAuthSession.objects.count(), 1)

    def test_skips_user_deleted_mid_request(self):
        # After a user deletes their own account in the same request, request.user has no pk;
        # syncing must not raise (it runs in the response phase of that very request).
        user = self._make_user()
        session = self._session(user)
        request = self._request(user, session)
        user.delete()

        sync_user_auth_session(request)  # must not raise

        self.assertEqual(UserAuthSession.objects.count(), 0)

    def test_delete_current_auth_session_removes_row(self):
        user = self._make_user()
        session = self._session(user)
        UserAuthSession.objects.create(user=user, session_key=session.session_key)
        request = self._request(user, session)

        delete_current_auth_session(request)

        self.assertFalse(UserAuthSession.objects.filter(session_key=session.session_key).exists())

    def test_skips_impersonated_session_and_clears_stray_row(self):
        user = self._make_user()
        session = self._session(user)
        # A stray row already exists for this key (e.g. created before impersonation began)
        UserAuthSession.objects.create(user=user, session_key=session.session_key)
        session[la_settings.USER_SESSION_FLAG] = "signed-original-user-pk"
        request = self._request(user, session)

        sync_user_auth_session(request)

        self.assertFalse(UserAuthSession.objects.filter(session_key=session.session_key).exists())


class TestRevokeSessions(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _logged_in_session(self, user: User) -> str:
        session = self.engine.SessionStore()
        session["_auth_user_id"] = str(user.pk)
        session.create()
        UserAuthSession.objects.create(user=user, session_key=session.session_key)
        return session.session_key

    def test_revoke_other_sessions_keeps_current(self):
        user = self._make_user()
        current = self._logged_in_session(user)
        other = self._logged_in_session(user)

        count = revoke_other_sessions(user, keep_session_key=current)

        self.assertEqual(count, 1)
        self.assertTrue(UserAuthSession.objects.filter(session_key=current).exists())
        self.assertFalse(UserAuthSession.objects.filter(session_key=other).exists())
        # backing django_session rows are gone for the revoked session, kept for current
        self.assertTrue(Session.objects.filter(session_key=current).exists())
        self.assertFalse(Session.objects.filter(session_key=other).exists())

    def test_revoke_other_sessions_with_no_keep_revokes_all(self):
        user = self._make_user()
        self._logged_in_session(user)
        self._logged_in_session(user)

        count = revoke_other_sessions(user, keep_session_key=None)

        self.assertEqual(count, 2)
        self.assertEqual(UserAuthSession.objects.filter(user=user).count(), 0)

    def test_revoke_other_sessions_does_not_touch_other_users(self):
        user = self._make_user()
        other_user = self._make_user()
        current = self._logged_in_session(user)
        self._logged_in_session(user)
        victim_key = self._logged_in_session(other_user)

        revoke_other_sessions(user, keep_session_key=current)

        self.assertTrue(UserAuthSession.objects.filter(session_key=victim_key).exists())
        self.assertTrue(Session.objects.filter(session_key=victim_key).exists())

    def test_revoke_user_auth_session_deletes_targeted_session(self):
        user = self._make_user()
        key = self._logged_in_session(user)
        row = UserAuthSession.objects.get(session_key=key)

        result = revoke_user_auth_session(user, row.id)

        self.assertTrue(result)
        self.assertFalse(UserAuthSession.objects.filter(id=row.id).exists())
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_revoke_user_auth_session_returns_false_for_other_users_session(self):
        user = self._make_user()
        other_user = self._make_user()
        other_key = self._logged_in_session(other_user)
        other_row = UserAuthSession.objects.get(session_key=other_key)

        result = revoke_user_auth_session(user, other_row.id)

        self.assertFalse(result)
        self.assertTrue(UserAuthSession.objects.filter(id=other_row.id).exists())
        self.assertTrue(Session.objects.filter(session_key=other_key).exists())

    def test_revoke_user_auth_session_returns_false_when_missing(self):
        user = self._make_user()
        self.assertFalse(revoke_user_auth_session(user, str(uuid.uuid4())))

    def test_revoke_user_auth_session_returns_false_for_invalid_id(self):
        user = self._make_user()
        self.assertFalse(revoke_user_auth_session(user, "not-a-uuid"))
