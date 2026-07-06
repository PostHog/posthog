import uuid
from importlib import import_module

from posthog.test.base import BaseTest, NonAtomicBaseTest

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.base import UpdateError

from asgiref.sync import async_to_sync
from loginas import settings as la_settings

from posthog.models import User
from posthog.session.models import Session


class TestSessionStore(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _store(self):
        return self.engine.SessionStore()

    def test_stamps_user_id_from_auth_user_id_on_create(self):
        user = self._make_user()
        store = self._store()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        store.create()

        row = Session.objects.get(session_key=store.session_key)
        self.assertEqual(row.user_id, user.pk)
        self.assertIsNotNone(row.last_activity)

    def test_anonymous_session_has_no_user_id(self):
        store = self._store()
        store["unrelated"] = "value"
        store.create()

        self.assertIsNone(Session.objects.get(session_key=store.session_key).user_id)

    def test_impersonation_session_is_not_attributed_to_the_user(self):
        user = self._make_user()
        store = self._store()
        store[SESSION_KEY] = str(user.pk)
        store[la_settings.USER_SESSION_FLAG] = "signed-original-user-pk"
        store.create()

        self.assertIsNone(Session.objects.get(session_key=store.session_key).user_id)

    def test_stamps_user_id_on_subsequent_save(self):
        # A session created anonymously then logged in (no cycle) must gain its user_id on save.
        user = self._make_user()
        store = self._store()
        store.create()
        store[SESSION_KEY] = str(user.pk)
        store.save()

        self.assertEqual(Session.objects.get(session_key=store.session_key).user_id, user.pk)

    def test_save_does_not_clobber_middleware_written_metadata(self):
        # The store must update only session-owned columns, leaving display metadata intact.
        user = self._make_user()
        store = self._store()
        store[SESSION_KEY] = str(user.pk)
        store.create()
        Session.objects.filter(session_key=store.session_key).update(
            short_user_agent="Chrome 135 on macOS", location="San Francisco, United States"
        )

        store["something"] = "changed"
        store.save()

        row = Session.objects.get(session_key=store.session_key)
        self.assertEqual(row.short_user_agent, "Chrome 135 on macOS")
        self.assertEqual(row.location, "San Francisco, United States")
        self.assertEqual(row.user_id, user.pk)

    def test_save_raises_update_error_when_row_is_gone(self):
        # signup.py relies on this: a save that updates zero rows must raise UpdateError, not pass.
        store = self._store()
        store["x"] = 1
        store.create()
        Session.objects.filter(session_key=store.session_key).delete()

        store["y"] = 2
        with self.assertRaises(UpdateError):
            store.save(must_create=False)


class TestSessionStoreAsync(NonAtomicBaseTest):
    """The async store path (asave/acreate_model_instance) must match the sync path: stamp user_id,
    skip impersonation, and leave middleware-written metadata intact. NonAtomicBaseTest so the async
    DB writes (run via sync_to_async) are committed and visible to the assertions.
    """

    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _store(self):
        return self.engine.SessionStore()

    def test_asave_stamps_user_id(self):
        user = self._make_user()
        store = self._store()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        async_to_sync(store.acreate)()  # async INSERT path → asave(must_create=True)

        self.assertEqual(Session.objects.get(session_key=store.session_key).user_id, user.pk)

    def test_asave_does_not_attribute_impersonation(self):
        user = self._make_user()
        store = self._store()
        store[SESSION_KEY] = str(user.pk)
        store[la_settings.USER_SESSION_FLAG] = "signed-original-user-pk"
        async_to_sync(store.acreate)()

        self.assertIsNone(Session.objects.get(session_key=store.session_key).user_id)

    def test_asave_does_not_clobber_metadata(self):
        user = self._make_user()
        store = self._store()
        store[SESSION_KEY] = str(user.pk)
        async_to_sync(store.acreate)()
        Session.objects.filter(session_key=store.session_key).update(
            short_user_agent="Chrome 135 on macOS", location="San Francisco, United States"
        )

        store["something"] = "changed"
        async_to_sync(store.asave)()

        row = Session.objects.get(session_key=store.session_key)
        self.assertEqual(row.short_user_agent, "Chrome 135 on macOS")
        self.assertEqual(row.location, "San Francisco, United States")
        self.assertEqual(row.user_id, user.pk)

    def test_asave_raises_update_error_when_row_is_gone(self):
        store = self._store()
        store["x"] = 1
        async_to_sync(store.acreate)()
        Session.objects.filter(session_key=store.session_key).delete()

        store["y"] = 2
        with self.assertRaises(UpdateError):
            async_to_sync(store.asave)()
