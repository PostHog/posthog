from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.test.utils import override_settings

from posthog.session.risk import (
    Baseline,
    Context,
    RiskSignal,
    RiskTier,
    current_request_context,
    evaluate_signals,
    risk_flags,
    tier_for,
    ua_signature,
)


class TestCurrentRequestContextTrustedIP(SimpleTestCase):
    def test_spoofed_forwarded_for_yields_no_geo(self):
        # An untrusted X-Forwarded-For chain must not become the geo source for risk scoring — a
        # cookie thief forging the header to the victim's location must not evade the geo signals.
        with override_settings(USE_X_FORWARDED_HOST=True, TRUST_ALL_PROXIES=False, TRUSTED_PROXIES="9.9.9.9"):
            request = RequestFactory().get("/", REMOTE_ADDR="9.9.9.9", HTTP_X_FORWARDED_FOR="1.2.3.4, 5.5.5.5")
            ctx = current_request_context(request)

        self.assertIsNone(ctx.country_code)
        self.assertIsNone(ctx.latitude)
        self.assertIsNone(ctx.longitude)


class TestUaSignature(BaseTest):
    def test_version_bump_same_signature(self):
        a = ua_signature("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/135.0.0.0 Safari/537.36")
        b = ua_signature("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/999.0.0.0 Safari/537.36")
        self.assertEqual(a, b)

    def test_browser_family_change_differs(self):
        chrome = ua_signature("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/135.0 Safari/537.36")
        firefox = ua_signature("Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0")
        self.assertNotEqual(chrome, firefox)

    def test_empty_is_none(self):
        self.assertIsNone(ua_signature(""))


class TestSignalsAndTiers(BaseTest):
    BASELINE_TIME = datetime(2026, 1, 1, tzinfo=UTC)

    def _baseline(self, **kw) -> Baseline:
        base: dict[str, Any] = {
            "latitude": 40.7,
            "longitude": -74.0,
            "country_code": "US",
            "ua_signature": "chrome|mac os x|pc",
            "baseline_at": self.BASELINE_TIME,
        }
        base.update(kw)
        return Baseline(**base)

    def _ctx(self, **kw) -> Context:
        base: dict[str, Any] = {
            "latitude": 40.7,
            "longitude": -74.0,
            "country_code": "US",
            "ua_signature": "chrome|mac os x|pc",
        }
        base.update(kw)
        return Context(**base)

    def test_impossible_travel_fires_high(self):
        b = self._baseline()
        # Tokyo, 10 minutes later
        ctx = self._ctx(latitude=35.6, longitude=139.7, country_code="JP")
        now = self.BASELINE_TIME + timedelta(minutes=10)
        signals = evaluate_signals(b, ctx, now=now)
        self.assertIn(RiskSignal.IMPOSSIBLE_TRAVEL, signals)
        self.assertEqual(tier_for(signals), RiskTier.HIGH)

    def test_short_hop_not_impossible(self):
        b = self._baseline()
        ctx = self._ctx(latitude=40.9, longitude=-74.2)  # < 500km
        signals = evaluate_signals(b, ctx, now=self.BASELINE_TIME + timedelta(minutes=10))
        self.assertNotIn(RiskSignal.IMPOSSIBLE_TRAVEL, signals)

    def test_impossible_travel_under_elapsed_floor_still_fires(self):
        # A huge distance in a gap shorter than the elapsed floor is the *most* impossible travel; the
        # floor only bounds the implied velocity, so the check must not be skipped for short gaps.
        b = self._baseline()
        ctx = self._ctx(latitude=35.6, longitude=139.7)  # Tokyo coords, same country to isolate the signal
        now = self.BASELINE_TIME + timedelta(seconds=30)  # well under RISK_ELAPSED_FLOOR_S (300)
        signals = evaluate_signals(b, ctx, now=now)
        self.assertIn(RiskSignal.IMPOSSIBLE_TRAVEL, signals)

    @override_settings(RISK_DISTANCE_FLOOR_KM=100_000.0)
    def test_distance_floor_read_from_settings_at_call_time(self):
        # Raising the floor above any real distance via settings must suppress the signal — proves the
        # threshold is read from settings per-call, not frozen at import.
        b = self._baseline()
        ctx = self._ctx(latitude=35.6, longitude=139.7)
        signals = evaluate_signals(b, ctx, now=self.BASELINE_TIME + timedelta(minutes=10))
        self.assertNotIn(RiskSignal.IMPOSSIBLE_TRAVEL, signals)

    def test_ua_change_alone_is_medium(self):
        b = self._baseline()
        ctx = self._ctx(ua_signature="firefox|mac os x|pc")
        signals = evaluate_signals(b, ctx, now=self.BASELINE_TIME + timedelta(minutes=10))
        self.assertEqual(signals, {RiskSignal.UA_CHANGE})
        self.assertEqual(tier_for(signals), RiskTier.MEDIUM)

    def test_two_mediums_escalate_to_high(self):
        signals = {RiskSignal.UA_CHANGE, RiskSignal.NEW_COUNTRY}
        self.assertEqual(tier_for(signals), RiskTier.HIGH)

    def test_null_baseline_no_signals(self):
        b = Baseline(latitude=None, longitude=None, country_code=None, ua_signature=None, baseline_at=None)
        signals = evaluate_signals(b, self._ctx(country_code="JP"), now=datetime(2026, 1, 2, tzinfo=UTC))
        self.assertEqual(signals, set())


class TestRiskFlags(BaseTest):
    @patch("posthog.session.risk.posthoganalytics.feature_enabled")
    def test_detection_off_forces_all_off(self, mock_flag):
        mock_flag.side_effect = lambda key, *a, **k: False
        flags = risk_flags(self.user)
        self.assertFalse(flags.detection)
        self.assertFalse(flags.step_up)
        self.assertFalse(flags.session_end)

    @patch("posthog.session.risk.posthoganalytics.feature_enabled")
    def test_step_up_requires_detection(self, mock_flag):
        mock_flag.side_effect = lambda key, *a, **k: key in {"session-risk-detection", "session-risk-step-up"}
        flags = risk_flags(self.user)
        self.assertTrue(flags.step_up)
        self.assertFalse(flags.session_end)
