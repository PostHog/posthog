from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest

from posthog.session.risk import Baseline, Context, RiskSignal, RiskTier, evaluate_signals, tier_for, ua_signature


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
    def _baseline(self, **kw) -> Baseline:
        base: dict[str, Any] = {
            "latitude": 40.7,
            "longitude": -74.0,
            "country_code": "US",
            "ua_signature": "chrome|mac os x|pc",
            "last_activity": datetime(2026, 1, 1, tzinfo=UTC),
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
        now = b.last_activity + timedelta(minutes=10)
        signals = evaluate_signals(b, ctx, now=now)
        self.assertIn(RiskSignal.IMPOSSIBLE_TRAVEL, signals)
        self.assertEqual(tier_for(signals), RiskTier.HIGH)

    def test_short_hop_not_impossible(self):
        b = self._baseline()
        ctx = self._ctx(latitude=40.9, longitude=-74.2)  # < 500km
        signals = evaluate_signals(b, ctx, now=b.last_activity + timedelta(minutes=10))
        self.assertNotIn(RiskSignal.IMPOSSIBLE_TRAVEL, signals)

    def test_ua_change_alone_is_medium(self):
        b = self._baseline()
        ctx = self._ctx(ua_signature="firefox|mac os x|pc")
        signals = evaluate_signals(b, ctx, now=b.last_activity + timedelta(minutes=10))
        self.assertEqual(signals, {RiskSignal.UA_CHANGE})
        self.assertEqual(tier_for(signals), RiskTier.MEDIUM)

    def test_two_mediums_escalate_to_high(self):
        signals = {RiskSignal.UA_CHANGE, RiskSignal.NEW_COUNTRY}
        self.assertEqual(tier_for(signals), RiskTier.HIGH)

    def test_null_baseline_no_signals(self):
        b = Baseline(latitude=None, longitude=None, country_code=None, ua_signature=None, last_activity=None)
        signals = evaluate_signals(b, self._ctx(country_code="JP"), now=datetime(2026, 1, 2, tzinfo=UTC))
        self.assertEqual(signals, set())
