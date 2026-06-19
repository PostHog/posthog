import time
from datetime import timedelta
from importlib import import_module
from typing import Any, cast

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.test import Client as DjangoClient
from django.urls import reverse
from django.utils import timezone

from posthog.models import User
from posthog.session.activity import session_public_id
from posthog.session.models import Session


class TestSessionEngineActivity(APIBaseTest):
    def test_authenticated_request_attributes_session_to_user(self):
        self.client.get("/api/users/@me/")

        row = Session.objects.get(session_key=self.client.session.session_key)
        self.assertEqual(row.user_id, self.user.pk)

    def test_anonymous_request_attributes_nothing(self):
        self.client.logout()

        self.client.get("/api/users/@me/")

        self.assertFalse(Session.objects.filter(user_id=self.user.pk).exists())

    def test_logout_removes_the_session_row(self):
        self.client.get("/api/users/@me/")
        key = self.client.session.session_key
        self.assertTrue(Session.objects.filter(session_key=key).exists())

        self.client.post("/logout")

        self.assertFalse(Session.objects.filter(session_key=key).exists())


class TestUserAuthSessionAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _other_session(self, user: User | None = None) -> Session:
        user = user or self.user
        store = self.engine.SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        store.create()
        return Session.objects.get(session_key=store.session_key)

    def _revoke_url(self, session: Session) -> str:
        return f"/api/users/@me/login_sessions/{session_public_id(session.session_key)}/"

    def test_list_returns_sessions_with_current_flag(self):
        self._other_session()

        response = self.client.get("/api/users/@me/login_sessions/")

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(sum(1 for s in data if s["is_current"]), 1)
        self.assertTrue(data[0]["is_current"])  # current session listed first

    def test_list_excludes_sensitive_fields(self):
        self._other_session()

        data = self.client.get("/api/users/@me/login_sessions/").json()

        for entry in data:
            self.assertNotIn("session_key", entry)
            self.assertNotIn("ip", entry)
            self.assertNotIn("user_agent", entry)

    def test_list_excludes_expired_sessions(self):
        stale = self._other_session()
        Session.objects.filter(session_key=stale.session_key).update(expire_date=timezone.now() - timedelta(days=1))

        data = self.client.get("/api/users/@me/login_sessions/").json()

        self.assertNotIn(str(session_public_id(stale.session_key)), [s["id"] for s in data])

    def test_list_only_returns_own_sessions(self):
        other_user = User.objects.create(email="someone-else@example.com", distinct_id="other")
        self._other_session(other_user)

        data = self.client.get("/api/users/@me/login_sessions/").json()

        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["is_current"])

    def test_revoke_session_deletes_it(self):
        other = self._other_session()

        response = self.client.delete(self._revoke_url(other))

        self.assertIn(response.status_code, (200, 204), response.content)
        self.assertFalse(Session.objects.filter(session_key=other.session_key).exists())

    def test_cannot_revoke_another_users_session(self):
        other_user = User.objects.create(email="victim@example.com", distinct_id="victim")
        victim = self._other_session(other_user)

        response = self.client.delete(self._revoke_url(victim))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Session.objects.filter(session_key=victim.session_key).exists())

    def test_revoke_others_keeps_current(self):
        first = self._other_session()
        second = self._other_session()

        response = self.client.post("/api/users/@me/login_sessions/revoke_others/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["revoked_count"], 2)
        self.assertFalse(Session.objects.filter(session_key__in=[first.session_key, second.session_key]).exists())
        self.assertEqual(self.client.get("/api/users/@me/").status_code, 200)  # current still works

    def test_personal_api_key_cannot_list_login_sessions(self):
        key = self.create_personal_api_key_with_scopes(["user:read"])
        self.client.logout()

        response = self.client.get("/api/users/@me/login_sessions/", HTTP_AUTHORIZATION=f"Bearer {key}")

        self.assertIn(response.status_code, (401, 403))

    def _make_session_stale(self) -> None:
        session = self.client.session
        session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time() - settings.SESSION_SENSITIVE_ACTIONS_AGE - 100
        session.save()

    def test_revoke_requires_reauth_on_stale_session(self):
        other = self._other_session()
        self._make_session_stale()

        response = self.client.delete(self._revoke_url(other))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "sensitive_action_required_reauth")
        self.assertTrue(Session.objects.filter(session_key=other.session_key).exists())

    def test_revoke_others_requires_reauth_on_stale_session(self):
        other = self._other_session()
        self._make_session_stale()

        response = self.client.post("/api/users/@me/login_sessions/revoke_others/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "sensitive_action_required_reauth")
        self.assertTrue(Session.objects.filter(session_key=other.session_key).exists())

    def test_listing_allowed_on_stale_session(self):
        self._other_session()
        self._make_session_stale()

        response = self.client.get("/api/users/@me/login_sessions/")

        self.assertEqual(response.status_code, 200, response.content)

    def test_actions_are_self_only_even_for_staff(self):
        self.user.is_staff = True
        self.user.save()
        victim_user = User.objects.create(email="victim-staff@example.com", distinct_id="victim-staff")
        victim = self._other_session(victim_user)

        listed = self.client.get(f"/api/users/{victim_user.uuid}/login_sessions/").json()
        self.assertNotIn(str(session_public_id(victim.session_key)), [s["id"] for s in listed])

        response = self.client.delete(
            f"/api/users/{victim_user.uuid}/login_sessions/{session_public_id(victim.session_key)}/"
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Session.objects.filter(session_key=victim.session_key).exists())


class TestUserAuthSessionImpersonation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.other_user = User.objects.create_and_join(
            self.organization, email="impersonated@posthog.com", password="123456"
        )
        self.user.is_staff = True
        self.user.save()
        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)

    def _impersonate(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "false", "reason": "test"},
            follow=True,
        )

    def test_get_list_allowed_while_impersonating(self):
        self._impersonate()

        response = self.client.get("/api/users/@me/login_sessions/")

        self.assertEqual(response.status_code, 200, response.content)

    def test_revoke_blocked_while_impersonating(self):
        self._impersonate()

        response = self.client.delete("/api/users/@me/login_sessions/00000000-0000-0000-0000-000000000000/")

        self.assertEqual(response.status_code, 403, response.content)

    def test_revoke_others_blocked_while_impersonating(self):
        self._impersonate()

        response = self.client.post("/api/users/@me/login_sessions/revoke_others/")

        self.assertEqual(response.status_code, 403, response.content)
