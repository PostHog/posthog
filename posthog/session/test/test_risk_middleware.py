import uuid
from datetime import timedelta
from importlib import import_module

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from loginas import settings as la_settings

from posthog.models import User
from posthog.session.middleware import SessionRiskMiddleware
from posthog.session.models import Session
from posthog.session.risk import Context, RiskFlags, RiskTier, evaluate_session_risk

IMPOSSIBLE_TRAVEL_CTX = Context(latitude=35.6, longitude=139.7, country_code="JP", ua_signature="chrome|mac os x|pc")
UA_CHANGE_CTX = Context(latitude=40.7, longitude=-74.0, country_code="US", ua_signature="firefox|mac os x|pc")


class TestEvaluateSessionRisk(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _make_user(self) -> User:
        return User.objects.create(email=f"risk-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

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

    def _seed_baseline(self, session_key: str) -> None:
        Session.objects.filter(session_key=session_key).update(
            latitude=40.7,
            longitude=-74.0,
            country_code="US",
            ua_signature="chrome|mac os x|pc",
            last_activity=timezone.now() - timedelta(minutes=10),
        )

    def _authed_request_with_baseline(self, user: User):
        key = self._login_session(user)
        self._seed_baseline(key)
        return self._request(user, key)

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(False, False, False))
    def test_detection_off_is_noop(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)
        self.assertNotIn("step_up_required", request.session)
        mock_capture.assert_not_called()

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, False))
    def test_report_only_does_not_set_flag_or_end(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        tier = evaluate_session_risk(request)

        self.assertEqual(tier, RiskTier.NONE)
        self.assertNotIn("step_up_required", request.session)
        mock_capture.assert_called_once()
        props = mock_capture.call_args.kwargs["properties"]
        self.assertFalse(props["enforced"])
        self.assertEqual(props["tier"], RiskTier.HIGH.name)
        self.assertIn("impossible_travel", props["signals"])

    @patch("posthog.session.risk.current_request_context", return_value=UA_CHANGE_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, False))
    def test_medium_sets_step_up_when_enabled(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        tier = evaluate_session_risk(request)

        self.assertEqual(tier, RiskTier.NONE)  # step-up is a side effect; middleware does not short-circuit
        self.assertTrue(request.session.get("step_up_required"))
        self.assertTrue(mock_capture.call_args.kwargs["properties"]["enforced"])

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, True))
    def test_high_effective_only_when_session_end_on(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.HIGH)
        self.assertTrue(mock_capture.call_args.kwargs["properties"]["enforced"])

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, False))
    def test_high_degrades_to_step_up_when_session_end_off(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)
        self.assertTrue(request.session.get("step_up_required"))

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_skips_impersonation(self, mock_flags, mock_capture, _ctx):
        user = self._make_user()
        request = self._authed_request_with_baseline(user)
        request.session[la_settings.USER_SESSION_FLAG] = "signed-original-user-pk"

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)
        mock_flags.assert_not_called()
        mock_capture.assert_not_called()

    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_skips_unauthenticated_request(self, mock_flags):
        from django.contrib.auth.models import AnonymousUser

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.session = self.engine.SessionStore()

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)
        mock_flags.assert_not_called()

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_missing_baseline_row_returns_none(self, _flags, mock_capture, _ctx):
        user = self._make_user()
        key = self._login_session(user)
        Session.objects.filter(session_key=key).delete()
        request = self._request(user, key)

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)
        mock_capture.assert_not_called()


class TestSessionRiskMiddleware(BaseTest):
    def setUp(self):
        super().setUp()
        self.engine = import_module(settings.SESSION_ENGINE)

    def _make_user(self) -> User:
        return User.objects.create(email=f"risk-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

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

    @patch("posthog.session.middleware.evaluate_session_risk", return_value=RiskTier.HIGH)
    def test_high_flushes_session_and_redirects(self, _evaluate):
        user = self._make_user()
        key = self._login_session(user)
        request = self._request(user, key)

        sentinel_called = False

        def get_response(_req):
            nonlocal sentinel_called
            sentinel_called = True
            return HttpResponse("ok")

        response = SessionRiskMiddleware(get_response)(request)

        self.assertFalse(sentinel_called)  # request short-circuited
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/login?reason=session_risk")
        self.assertFalse(Session.objects.filter(session_key=key).exists())  # flushed server-side

    @patch("posthog.session.middleware.evaluate_session_risk", return_value=RiskTier.NONE)
    def test_non_high_passes_through(self, _evaluate):
        user = self._make_user()
        key = self._login_session(user)
        request = self._request(user, key)

        response = SessionRiskMiddleware(lambda _req: HttpResponse("ok"))(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertTrue(Session.objects.filter(session_key=key).exists())

    def test_unauthenticated_request_skips_evaluation(self):
        from django.contrib.auth.models import AnonymousUser

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.session = self.engine.SessionStore()

        with patch("posthog.session.middleware.evaluate_session_risk") as mock_evaluate:
            response = SessionRiskMiddleware(lambda _req: HttpResponse("ok"))(request)

        mock_evaluate.assert_not_called()
        self.assertEqual(response.status_code, 200)
