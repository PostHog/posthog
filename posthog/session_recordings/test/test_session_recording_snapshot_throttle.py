from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.session_recordings.session_recording_api import (
    SNAPSHOT_DEFAULT_TIER,
    SNAPSHOT_RATES,
    SNAPSHOTS_TIER_CACHE_TTL_SECONDS,
    SnapshotsBurstRateThrottle,
    _org_tier_from_features,
    _snapshot_rates,
    get_cached_org_tier,
)


def _fake_personal_api_key_request():
    req = type("FakeRequest", (), {"META": {}, "auth": "phx_fake"})()
    req.successful_authenticator = PersonalAPIKeyAuthentication()
    return req


def _fake_session_auth_request():
    return type("FakeRequest", (), {"META": {}, "auth": None, "successful_authenticator": None})()


class TestOrgTierFromFeatures(BaseTest):
    @parameterized.expand(
        [
            ("none_features", None, "free"),
            ("empty_features", [], "free"),
            ("paid_with_zapier", [{"key": "zapier", "name": "Zapier"}], "paid"),
            (
                "paid_with_multiple_features",
                [{"key": "zapier", "name": "Zapier"}, {"key": "group_analytics", "name": "Group Analytics"}],
                "paid",
            ),
            (
                "enterprise_with_saml",
                [{"key": "saml", "name": "SAML"}, {"key": "zapier", "name": "Zapier"}],
                "enterprise",
            ),
            (
                "enterprise_with_scim",
                [{"key": "scim", "name": "SCIM"}, {"key": "zapier", "name": "Zapier"}],
                "enterprise",
            ),
            (
                "enterprise_with_both",
                [{"key": "saml", "name": "SAML"}, {"key": "scim", "name": "SCIM"}],
                "enterprise",
            ),
            (
                "ignores_falsy_entries",
                [None, {"key": "zapier", "name": "Zapier"}, False, 0],
                "paid",
            ),
        ]
    )
    def test_tier_detection(self, _name: str, features: list | None, expected_tier: str) -> None:
        assert _org_tier_from_features(features) == expected_tier


class TestGetCachedOrgTier(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def tearDown(self) -> None:
        super().tearDown()
        cache.clear()

    def test_returns_free_for_org_with_no_features(self) -> None:
        self.organization.available_product_features = None
        self.organization.save()

        tier = get_cached_org_tier(self.team.pk)

        assert tier == "free"

    def test_returns_paid_for_org_with_features(self) -> None:
        self.organization.available_product_features = [{"key": "zapier", "name": "Zapier"}]
        self.organization.save()

        tier = get_cached_org_tier(self.team.pk)

        assert tier == "paid"

    def test_returns_enterprise_for_org_with_saml(self) -> None:
        self.organization.available_product_features = [
            {"key": "saml", "name": "SAML"},
            {"key": "zapier", "name": "Zapier"},
        ]
        self.organization.save()

        tier = get_cached_org_tier(self.team.pk)

        assert tier == "enterprise"

    def test_caches_result(self) -> None:
        self.organization.available_product_features = [{"key": "zapier", "name": "Zapier"}]
        self.organization.save()

        get_cached_org_tier(self.team.pk)

        cached_value = cache.get(f"snapshots_org_tier_{self.team.pk}")
        assert cached_value == "paid"

    def test_uses_cached_value_on_second_call(self) -> None:
        cache.set(f"snapshots_org_tier_{self.team.pk}", "enterprise", SNAPSHOTS_TIER_CACHE_TTL_SECONDS)

        self.organization.available_product_features = None
        self.organization.save()

        tier = get_cached_org_tier(self.team.pk)

        assert tier == "enterprise"

    def test_returns_free_for_nonexistent_team(self) -> None:
        tier = get_cached_org_tier(999999)

        assert tier == "free"


class TestSnapshotRatesConfig(BaseTest):
    @parameterized.expand(
        [
            ("free_burst", "free", "snapshots_burst", "60/minute"),
            ("free_sustained", "free", "snapshots_sustained", "300/hour"),
            ("paid_burst", "paid", "snapshots_burst", "90/minute"),
            ("paid_sustained", "paid", "snapshots_sustained", "500/hour"),
            ("enterprise_burst", "enterprise", "snapshots_burst", "120/minute"),
            ("enterprise_sustained", "enterprise", "snapshots_sustained", "600/hour"),
        ]
    )
    def test_rate_config(self, _name: str, tier: str, scope: str, expected_rate: str) -> None:
        assert SNAPSHOT_RATES[tier][scope] == expected_rate

    def test_default_tier_exists_in_rates(self) -> None:
        assert SNAPSHOT_DEFAULT_TIER in SNAPSHOT_RATES

    def test_unknown_tier_falls_back_to_default(self) -> None:
        throttle = SnapshotsBurstRateThrottle()

        throttle._apply_tier_rates("mystery_tier")

        expected_rate = SNAPSHOT_RATES[SNAPSHOT_DEFAULT_TIER]["snapshots_burst"]
        assert throttle.rate == expected_rate


class TestTierAwareSnapshotThrottle(BaseTest):
    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", side_effect=Exception("db gone"))
    def test_tier_lookup_error_falls_back_to_default_rates(self, _mock_tier: object) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        expected_rate = SNAPSHOT_RATES[SNAPSHOT_DEFAULT_TIER]["snapshots_burst"]
        assert throttle.rate == expected_rate

    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier")
    def test_skips_tier_lookup_for_non_personal_api_key_requests(self, mock_tier) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()
        original_rate = throttle.rate

        throttle.allow_request(request=_fake_session_auth_request(), view=view)

        mock_tier.assert_not_called()
        assert throttle.rate == original_rate

    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", return_value="paid")
    def test_applies_tier_rates_for_personal_api_key_requests(self, _mock_tier) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        assert throttle.rate == SNAPSHOT_RATES["paid"]["snapshots_burst"]

    def test_missing_team_id_applies_free_tier_rates(self) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": None})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        expected_rate = SNAPSHOT_RATES[SNAPSHOT_DEFAULT_TIER]["snapshots_burst"]
        assert throttle.rate == expected_rate

    @override_settings(SNAPSHOT_RATE_PAID_BURST="200/minute")
    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", return_value="paid")
    def test_rate_limits_are_configurable_via_django_settings(self, _mock_tier) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        assert throttle.rate == "200/minute"


class TestSnapshotRatesFromSettings(BaseTest):
    @override_settings(SNAPSHOT_RATE_FREE_BURST="999/minute")
    def test_snapshot_rates_reads_from_settings(self) -> None:
        rates = _snapshot_rates()

        assert rates["free"]["snapshots_burst"] == "999/minute"
