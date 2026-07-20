import uuid
from datetime import timedelta
from importlib import import_module

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone

from loginas import settings as la_settings
from parameterized import parameterized

from posthog.models import User
from posthog.session.middleware import SessionRiskMiddleware
from posthog.session.models import Session
from posthog.session.risk import Context, RiskFlags, RiskTier, evaluate_session_risk

IMPOSSIBLE_TRAVEL_CTX = Context(latitude=35.6, longitude=139.7, country_code="JP", ua_signature="chrome|mac os x|pc")
UA_CHANGE_CTX = Context(latitude=40.7, longitude=-74.0, country_code="US", ua_signature="firefox|mac os x|pc")
STABLE_CTX = Context(latitude=40.7, longitude=-74.0, country_code="US", ua_signature="chrome|mac os x|pc")
NEARBY_CTX = Context(latitude=41.0, longitude=-74.5, country_code="US", ua_signature="chrome|mac os x|pc")
NO_GEO_CTX = Context(latitude=None, longitude=None, country_code=None, ua_signature="chrome|mac os x|pc")


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
            baseline_at=timezone.now() - timedelta(minutes=10),
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

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, False))
    def test_telemetry_event_carries_no_pii(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        evaluate_session_risk(request)

        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args.kwargs["event"], "session_risk_detected")
        props = mock_capture.call_args.kwargs["properties"]
        self.assertIn("signals", props)
        self.assertIn("tier", props)
        for forbidden in ("ip", "session_key", "latitude", "longitude"):
            self.assertNotIn(forbidden, props)

    @patch("posthog.session.risk.current_request_context", return_value=UA_CHANGE_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, False))
    def test_medium_sets_step_up_when_enabled(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        tier = evaluate_session_risk(request)

        self.assertEqual(tier, RiskTier.NONE)  # step-up is a side effect; middleware does not short-circuit
        self.assertTrue(request.session.get("step_up_required"))
        self.assertTrue(mock_capture.call_args.kwargs["properties"]["enforced"])

    @patch("posthog.session.risk.current_request_context", return_value=UA_CHANGE_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, False))
    def test_step_up_persisted_immediately(self, _flags, _capture, _ctx):
        # The flag must be written to the store now, not left only in memory: a 5xx response skips
        # Django's SessionMiddleware save(), which would otherwise drop the step-up requirement.
        request = self._authed_request_with_baseline(self._make_user())

        evaluate_session_risk(request)

        reloaded = self.engine.SessionStore(session_key=request.session.session_key)
        self.assertTrue(reloaded.get("step_up_required"))

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, True))
    def test_high_effective_only_when_session_end_on(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.HIGH)
        self.assertTrue(mock_capture.call_args.kwargs["properties"]["enforced"])

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture", side_effect=RuntimeError("telemetry down"))
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, True))
    def test_telemetry_failure_does_not_break_evaluation(self, _flags, _capture, _ctx):
        # A capture error must not propagate out of the request-phase middleware and 500 the request.
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.HIGH)

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, False))
    def test_high_degrades_to_step_up_when_session_end_off(self, _flags, mock_capture, _ctx):
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)
        self.assertTrue(request.session.get("step_up_required"))

    @parameterized.expand([("within_cooldown", 3600.0, 1), ("cooldown_elapsed", 0.0, 2)])
    def test_persistent_anomaly_emits_once_per_cooldown(self, _name, cooldown, expected_calls):
        # A flagged session is re-scored on every request; the same anomaly must emit once per cooldown
        # window, not once per request (the bug that inflated per-user counts into the hundreds).
        request = self._authed_request_with_baseline(self._make_user())
        with (
            override_settings(RISK_REEMIT_COOLDOWN_S=cooldown),
            patch("posthog.session.risk.current_request_context", return_value=UA_CHANGE_CTX),
            patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, False)),
            patch("posthog.session.risk.posthoganalytics.capture") as mock_capture,
        ):
            evaluate_session_risk(request)
            evaluate_session_risk(request)
        self.assertEqual(mock_capture.call_count, expected_calls)

    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_new_signature_re_emits_within_cooldown(self, _flags, mock_capture):
        # An escalation to a different anomaly (MEDIUM ua_change -> HIGH impossible travel) is a new
        # incident and must re-emit even inside the cooldown window.
        request = self._authed_request_with_baseline(self._make_user())
        with patch("posthog.session.risk.current_request_context", return_value=UA_CHANGE_CTX):
            evaluate_session_risk(request)
        with patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX):
            evaluate_session_risk(request)
        self.assertEqual(mock_capture.call_count, 2)

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, True))
    def test_dedup_suppresses_telemetry_not_session_end(self, _flags, mock_capture, _ctx):
        # Dedup gates only the emit, never the acted-on tier: a repeated HIGH request within the
        # cooldown still returns HIGH so the middleware ends the session.
        request = self._authed_request_with_baseline(self._make_user())
        first = evaluate_session_risk(request)
        second = evaluate_session_risk(request)
        self.assertEqual(first, RiskTier.HIGH)
        self.assertEqual(second, RiskTier.HIGH)
        mock_capture.assert_called_once()

    @patch("posthog.session.risk.current_request_context", return_value=UA_CHANGE_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    def test_step_up_applied_when_enabled_after_report_only(self, mock_capture, _ctx):
        # Enabling step-up mid-session must enforce an already-flagged session even though the
        # identical anomaly's telemetry is deduped within the cooldown: enforcement is independent
        # of the emit gate, otherwise a rollout flip leaves flagged sessions unenforced for an hour.
        request = self._authed_request_with_baseline(self._make_user())
        with patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, False)):
            evaluate_session_risk(request)  # report-only: emits telemetry, sets no step-up
        self.assertNotIn("step_up_required", request.session)
        with patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, False)):
            evaluate_session_risk(request)  # step-up now enabled, same anomaly within cooldown
        self.assertTrue(request.session.get("step_up_required"))
        mock_capture.assert_called_once()  # telemetry stays deduped

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

    @patch("posthog.session.risk.current_request_context", return_value=NEARBY_CTX)
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_low_risk_request_establishes_null_baseline(self, _flags, _ctx):
        # First low-risk request after login (NULL baseline) establishes the anchor from its own geo.
        user = self._make_user()
        key = self._login_session(user)

        self.assertEqual(evaluate_session_risk(self._request(user, key)), RiskTier.NONE)

        row = Session.objects.get(session_key=key)
        self.assertEqual(row.latitude, 41.0)
        self.assertEqual(row.country_code, "US")
        self.assertIsNotNone(row.baseline_at)

    @patch("posthog.session.risk.current_request_context", return_value=NEARBY_CTX)
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_low_risk_request_rolls_baseline_forward(self, _flags, _ctx):
        # A plausible move on a stale baseline (10 min old) advances the known-good snapshot.
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)

        row = Session.objects.get(session_key=request.session.session_key)
        self.assertEqual(row.latitude, 41.0)
        self.assertEqual(row.longitude, -74.5)

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_suspicious_request_does_not_advance_baseline(self, _flags, _capture, _ctx):
        # The #1 fix: a suspicious request must never overwrite the reference it is scored against.
        request = self._authed_request_with_baseline(self._make_user())

        evaluate_session_risk(request)

        row = Session.objects.get(session_key=request.session.session_key)
        self.assertEqual(row.latitude, 40.7)  # still NYC, not poisoned to Tokyo
        self.assertEqual(row.country_code, "US")

    @patch("posthog.session.risk.current_request_context", return_value=IMPOSSIBLE_TRAVEL_CTX)
    @patch("posthog.session.risk.posthoganalytics.capture")
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, False, True))
    def test_attacker_cannot_erase_detection_over_repeated_requests(self, _flags, _capture, _ctx):
        # Because the baseline is never poisoned, a replayed stolen cookie keeps tripping HIGH rather
        # than self-erasing after the first hit.
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.HIGH)
        self.assertEqual(evaluate_session_risk(request), RiskTier.HIGH)

    @patch("posthog.session.risk.current_request_context", return_value=STABLE_CTX)
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_baseline_advance_throttled_within_window(self, _flags, _ctx):
        # A fresh baseline (30s old) is not rewritten on every request — refreshes are throttled.
        user = self._make_user()
        key = self._login_session(user)
        recent = timezone.now() - timedelta(seconds=30)  # within RISK_BASELINE_REFRESH_S (300)
        Session.objects.filter(session_key=key).update(
            latitude=40.7, longitude=-74.0, country_code="US", ua_signature="chrome|mac os x|pc", baseline_at=recent
        )

        self.assertEqual(evaluate_session_risk(self._request(user, key)), RiskTier.NONE)

        row = Session.objects.get(session_key=key)
        assert row.baseline_at is not None
        self.assertAlmostEqual(row.baseline_at.timestamp(), recent.timestamp(), delta=1)  # not refreshed to now

    @patch("posthog.session.risk.current_request_context", return_value=NO_GEO_CTX)
    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(True, True, True))
    def test_no_geo_request_does_not_corrupt_baseline(self, _flags, _ctx):
        # A geo-less low-risk request keeps the last known-good geo intact (geo stays paired with its
        # timestamp), rather than nulling it.
        request = self._authed_request_with_baseline(self._make_user())

        self.assertEqual(evaluate_session_risk(request), RiskTier.NONE)

        row = Session.objects.get(session_key=request.session.session_key)
        self.assertEqual(row.latitude, 40.7)


@override_settings(SESSION_RISK_ENABLED=True)
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

    @patch("posthog.session.middleware.evaluate_session_risk", return_value=RiskTier.HIGH)
    def test_high_only_ends_current_session_other_sessions_survive(self, _evaluate):
        user = self._make_user()
        current_key = self._login_session(user)
        other_key = self._login_session(user)
        request = self._request(user, current_key)

        SessionRiskMiddleware(lambda _req: HttpResponse("ok"))(request)

        self.assertFalse(Session.objects.filter(session_key=current_key).exists())
        self.assertTrue(Session.objects.filter(session_key=other_key).exists())

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

    @patch("posthog.session.risk.risk_flags", return_value=RiskFlags(detection=True, step_up=True, session_end=False))
    @patch(
        "posthog.session.risk.get_geoip_location",
        return_value={"latitude": 40.7, "longitude": -74.0, "country_code": "US"},
    )
    def test_real_medium_sets_step_up_and_passes_through(self, _geoip, _flags):
        # Real evaluate_session_risk through the middleware (only geoip + flags mocked): same geo as the
        # baseline but a different UA family is a UA_CHANGE → MEDIUM. With step-up on (session-end off)
        # it sets step_up_required and passes the request through rather than flushing.
        user = self._make_user()
        key = self._login_session(user)
        Session.objects.filter(session_key=key).update(
            latitude=40.7,
            longitude=-74.0,
            country_code="US",
            ua_signature="chrome|mac os x|pc",
            baseline_at=timezone.now() - timedelta(minutes=30),
        )
        request = self._request(user, key)
        request.META["HTTP_USER_AGENT"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0"
        )

        response = SessionRiskMiddleware(lambda _req: HttpResponse("ok"))(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(request.session.get("step_up_required"))
        self.assertTrue(Session.objects.filter(session_key=key).exists())
