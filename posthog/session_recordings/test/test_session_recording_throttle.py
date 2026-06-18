from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.auth import (
    PersonalAPIKeyAuthentication,
    SharingAccessTokenAuthentication,
    SharingPasswordProtectedAuthentication,
)
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.utils import hash_key_value
from posthog.session_recordings.session_recording_api import (
    LISTING_RATES,
    REPLAY_TIER_CACHE_TTL_SECONDS,
    SNAPSHOT_DEFAULT_TIER,
    SNAPSHOT_RATES,
    ListingBurstRateThrottle,
    SessionRecordingViewSet,
    SharingTokenReplayThrottle,
    SnapshotsBurstRateThrottle,
    SnapshotsSustainedRateThrottle,
    get_cached_org_tier,
    listing_rates,
    snapshot_rates,
)


def _fake_personal_api_key_request():
    req = type("FakeRequest", (), {"META": {}, "auth": "phx_fake"})()
    req.successful_authenticator = PersonalAPIKeyAuthentication()
    return req


def _fake_session_auth_request():
    return type("FakeRequest", (), {"META": {}, "auth": None, "successful_authenticator": None})()


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

        cached_value = cache.get(f"replay_org_tier_v2_{self.team.pk}")
        assert cached_value == "paid"

    def test_uses_cached_value_on_second_call(self) -> None:
        cache.set(f"replay_org_tier_v2_{self.team.pk}", "enterprise", REPLAY_TIER_CACHE_TTL_SECONDS)

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
            ("free_burst", "free", "snapshots_burst", "12/minute"),
            ("free_sustained", "free", "snapshots_sustained", "60/hour"),
            ("paid_burst", "paid", "snapshots_burst", "60/minute"),
            ("paid_sustained", "paid", "snapshots_sustained", "300/hour"),
            ("enterprise_burst", "enterprise", "snapshots_burst", "100/minute"),
            ("enterprise_sustained", "enterprise", "snapshots_sustained", "400/hour"),
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
        assert throttle.scope == "snapshots_burst_free"


class TestTierAwareSnapshotThrottle(BaseTest):
    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", side_effect=Exception("db gone"))
    def test_tier_lookup_error_falls_back_to_default_rates(self, _mock_tier: object) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        expected_rate = SNAPSHOT_RATES[SNAPSHOT_DEFAULT_TIER]["snapshots_burst"]
        assert throttle.rate == expected_rate
        assert throttle.scope == "snapshots_burst_free"

    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier")
    def test_skips_tier_lookup_for_non_personal_api_key_requests(self, mock_tier) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()
        original_rate = throttle.rate

        throttle.allow_request(request=_fake_session_auth_request(), view=view)

        mock_tier.assert_not_called()
        assert throttle.rate == original_rate
        assert throttle.scope == "snapshots_burst"

    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", return_value="paid")
    def test_applies_tier_rates_for_personal_api_key_requests(self, _mock_tier) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        assert throttle.rate == SNAPSHOT_RATES["paid"]["snapshots_burst"]
        assert throttle.scope == "snapshots_burst_paid"

    def test_missing_team_id_applies_free_tier_rates(self) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": None})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        expected_rate = SNAPSHOT_RATES[SNAPSHOT_DEFAULT_TIER]["snapshots_burst"]
        assert throttle.rate == expected_rate
        assert throttle.scope == "snapshots_burst_free"

    @override_settings(SNAPSHOT_RATE_PAID_BURST="200/minute")
    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", return_value="paid")
    def test_rate_limits_are_configurable_via_django_settings(self, _mock_tier) -> None:
        throttle = SnapshotsBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        assert throttle.rate == "200/minute"


class TestApplyTierRatesSetsScope(BaseTest):
    @parameterized.expand(
        [
            ("burst_free", SnapshotsBurstRateThrottle, "free", "snapshots_burst_free"),
            ("burst_paid", SnapshotsBurstRateThrottle, "paid", "snapshots_burst_paid"),
            ("burst_enterprise", SnapshotsBurstRateThrottle, "enterprise", "snapshots_burst_enterprise"),
            ("sustained_free", SnapshotsSustainedRateThrottle, "free", "snapshots_sustained_free"),
            ("sustained_paid", SnapshotsSustainedRateThrottle, "paid", "snapshots_sustained_paid"),
            ("sustained_enterprise", SnapshotsSustainedRateThrottle, "enterprise", "snapshots_sustained_enterprise"),
        ]
    )
    def test_scope_includes_tier(self, _name: str, throttle_class: type, tier: str, expected_scope: str) -> None:
        throttle = throttle_class()

        throttle._apply_tier_rates(tier)

        assert throttle.scope == expected_scope


class TestSnapshotRatesFromSettings(BaseTest):
    @override_settings(SNAPSHOT_RATE_FREE_BURST="999/minute")
    def test_snapshot_rates_reads_from_settings(self) -> None:
        rates = snapshot_rates()

        assert rates["free"]["snapshots_burst"] == "999/minute"


class TestListingRatesConfig(BaseTest):
    @parameterized.expand(
        [
            ("free_burst", "free", "listing_burst", "12/minute"),
            ("free_sustained", "free", "listing_sustained", "60/hour"),
            ("paid_burst", "paid", "listing_burst", "60/minute"),
            ("paid_sustained", "paid", "listing_sustained", "300/hour"),
            ("enterprise_burst", "enterprise", "listing_burst", "100/minute"),
            ("enterprise_sustained", "enterprise", "listing_sustained", "400/hour"),
        ]
    )
    def test_rate_config(self, _name: str, tier: str, scope: str, expected_rate: str) -> None:
        assert LISTING_RATES[tier][scope] == expected_rate

    def test_default_tier_exists_in_rates(self) -> None:
        assert SNAPSHOT_DEFAULT_TIER in LISTING_RATES

    def test_unknown_tier_falls_back_to_default(self) -> None:
        throttle = ListingBurstRateThrottle()

        throttle._apply_tier_rates("mystery_tier")

        expected_rate = LISTING_RATES[SNAPSHOT_DEFAULT_TIER]["listing_burst"]
        assert throttle.rate == expected_rate


class TestTierAwareListingThrottle(BaseTest):
    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", side_effect=Exception("db gone"))
    def test_tier_lookup_error_falls_back_to_default_rates(self, _mock_tier: object) -> None:
        throttle = ListingBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        expected_rate = LISTING_RATES[SNAPSHOT_DEFAULT_TIER]["listing_burst"]
        assert throttle.rate == expected_rate

    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier")
    def test_skips_tier_lookup_for_non_personal_api_key_requests(self, mock_tier) -> None:
        throttle = ListingBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()
        original_rate = throttle.rate

        throttle.allow_request(request=_fake_session_auth_request(), view=view)

        mock_tier.assert_not_called()
        assert throttle.rate == original_rate

    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", return_value="paid")
    def test_applies_tier_rates_for_personal_api_key_requests(self, _mock_tier) -> None:
        throttle = ListingBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        assert throttle.rate == LISTING_RATES["paid"]["listing_burst"]

    def test_missing_team_id_applies_free_tier_rates(self) -> None:
        throttle = ListingBurstRateThrottle()
        view = type("FakeView", (), {"team_id": None})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        expected_rate = LISTING_RATES[SNAPSHOT_DEFAULT_TIER]["listing_burst"]
        assert throttle.rate == expected_rate

    @override_settings(LISTING_RATE_PAID_BURST="200/minute")
    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", return_value="paid")
    def test_rate_limits_are_configurable_via_django_settings(self, _mock_tier) -> None:
        throttle = ListingBurstRateThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        throttle.allow_request(request=_fake_personal_api_key_request(), view=view)

        assert throttle.rate == "200/minute"


class TestListingRatesFromSettings(BaseTest):
    @override_settings(LISTING_RATE_FREE_BURST="999/minute")
    def test_listing_rates_reads_from_settings(self) -> None:
        rates = listing_rates()

        assert rates["free"]["listing_burst"] == "999/minute"


class TestSnapshotAndListingThrottlesUseIndependentRates(BaseTest):
    def test_snapshot_and_listing_throttles_use_different_rate_tables(self) -> None:
        snapshot_throttle = SnapshotsBurstRateThrottle()
        listing_throttle = ListingBurstRateThrottle()

        assert snapshot_throttle._get_rates() == snapshot_rates()
        assert listing_throttle._get_rates() == listing_rates()
        assert snapshot_throttle._get_rates() == snapshot_rates()
        assert listing_throttle._get_rates() == listing_rates()


def _counter_value(location: str, auth_type: str) -> float:
    from posthog.session_recordings.session_recording_api import SESSION_RECORDING_THROTTLED

    sample = SESSION_RECORDING_THROTTLED.labels(location=location, auth_type=auth_type)
    return sample._value.get()  # prometheus_client's internal counter accessor


def _fake_sharing_token_request(token: str, auth_cls: type = SharingAccessTokenAuthentication):
    auth = auth_cls()
    auth.sharing_configuration = SharingConfiguration(access_token=token, enabled=True)
    return type("FakeRequest", (), {"META": {}, "auth": None, "successful_authenticator": auth})()


class TestSharingTokenReplayThrottle(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def tearDown(self) -> None:
        super().tearDown()
        cache.clear()

    def test_cache_key_uses_hashed_token_not_raw(self) -> None:
        # Raw bearer tokens must never appear in cache keys (Redis MONITOR / log leakage).
        throttle = SharingTokenReplayThrottle()

        key = throttle.get_cache_key(_fake_sharing_token_request("token-abc"), view=None)

        assert key is not None
        assert "token-abc" not in key
        assert hash_key_value("token-abc") in key
        assert throttle.scope in key

    def test_different_tokens_have_different_cache_keys(self) -> None:
        throttle = SharingTokenReplayThrottle()

        key_a = throttle.get_cache_key(_fake_sharing_token_request("token-a"), view=None)
        key_b = throttle.get_cache_key(_fake_sharing_token_request("token-b"), view=None)

        assert key_a != key_b

    def test_same_token_from_different_requests_shares_one_bucket(self) -> None:
        throttle = SharingTokenReplayThrottle()

        key_first = throttle.get_cache_key(_fake_sharing_token_request("token-shared"), view=None)
        key_second = throttle.get_cache_key(_fake_sharing_token_request("token-shared"), view=None)

        assert key_first == key_second

    def test_password_protected_auth_shares_bucket_with_access_token_auth(self) -> None:
        # Both authenticators expose `sharing_configuration.access_token` — same recording, same bucket.
        throttle = SharingTokenReplayThrottle()

        key_access = throttle.get_cache_key(
            _fake_sharing_token_request("token-x", SharingAccessTokenAuthentication), view=None
        )
        key_password = throttle.get_cache_key(
            _fake_sharing_token_request("token-x", SharingPasswordProtectedAuthentication), view=None
        )

        assert key_access == key_password

    def test_returns_none_cache_key_when_no_sharing_configuration(self) -> None:
        # Defensive guard against misrouted requests.
        throttle = SharingTokenReplayThrottle()
        request = type("FakeRequest", (), {"META": {}, "auth": None, "successful_authenticator": None})()

        assert throttle.get_cache_key(request, view=None) is None

    def test_rate_reads_from_settings_default(self) -> None:
        throttle = SharingTokenReplayThrottle()

        assert throttle.rate == "600/minute"

    @override_settings(REPLAY_SHARING_TOKEN_RATE="42/minute")
    def test_rate_is_configurable_via_settings(self) -> None:
        throttle = SharingTokenReplayThrottle()

        assert throttle.rate == "42/minute"

    @patch("posthog.session_recordings.session_recording_api.is_rate_limit_enabled", return_value=False)
    def test_allow_request_short_circuits_when_kill_switch_off(self, _mock) -> None:
        throttle = SharingTokenReplayThrottle()
        view = type("FakeView", (), {"team_id": 1})()

        for _ in range(10_000):
            assert throttle.allow_request(_fake_sharing_token_request("token"), view=view) is True

    @patch("posthog.session_recordings.session_recording_api.is_rate_limit_enabled", return_value=True)
    @patch("posthog.session_recordings.session_recording_api.team_is_allowed_to_bypass_throttle", return_value=True)
    def test_allow_request_short_circuits_for_bypass_listed_team(self, _mock_bypass, _mock_enabled) -> None:
        # Without enabling the kill switch, the test would short-circuit on it and never exercise bypass.
        throttle = SharingTokenReplayThrottle()
        view = type("FakeView", (), {"team_id": 7})()

        for _ in range(10_000):
            assert throttle.allow_request(_fake_sharing_token_request("token"), view=view) is True

    @patch("posthog.session_recordings.session_recording_api.is_rate_limit_enabled", return_value=True)
    @override_settings(REPLAY_SHARING_TOKEN_RATE="2/minute")
    def test_allow_request_emits_throttled_counter_on_rejection(self, _mock) -> None:
        throttle = SharingTokenReplayThrottle()
        view = type("FakeView", (), {"team_id": 1})()
        before = _counter_value("replay_sharing_token", "sharing_token")

        # Burn the bucket then attempt one more — only the rejected one bumps the counter.
        for _ in range(2):
            throttle.allow_request(_fake_sharing_token_request("token-counted"), view=view)
        throttle.allow_request(_fake_sharing_token_request("token-counted"), view=view)

        after = _counter_value("replay_sharing_token", "sharing_token")
        assert after - before == 1


class TestSessionRecordingViewSetThrottleSelection(BaseTest):
    def _viewset(self, action: str, authenticator) -> SessionRecordingViewSet:
        viewset = SessionRecordingViewSet()
        viewset.action = action
        request = Request(APIRequestFactory().get("/"))
        request._authenticator = authenticator  # type: ignore[attr-defined]  # backs read-only @property
        viewset.request = request  # ty: ignore[invalid-assignment]
        return viewset

    @parameterized.expand(
        [
            ("access_token", SharingAccessTokenAuthentication),
            ("password_protected", SharingPasswordProtectedAuthentication),
        ]
    )
    def test_sharing_token_requests_only_use_per_token_throttle(self, _name: str, auth_cls: type) -> None:
        auth = auth_cls()
        auth.sharing_configuration = SharingConfiguration(access_token="tok", enabled=True)
        viewset = self._viewset(action="snapshots", authenticator=auth)

        throttles = viewset.get_throttles()

        assert len(throttles) == 1
        assert isinstance(throttles[0], SharingTokenReplayThrottle)

    def test_sharing_token_on_list_does_not_include_listing_throttles(self) -> None:
        # Defence in depth: `list` isn't sharing-enabled, but if it ever is, the per-token cap must be the only throttle.
        auth = SharingAccessTokenAuthentication()
        auth.sharing_configuration = SharingConfiguration(access_token="tok", enabled=True)
        viewset = self._viewset(action="list", authenticator=auth)

        throttles = viewset.get_throttles()

        assert all(not isinstance(t, ListingBurstRateThrottle) for t in throttles)
        assert any(isinstance(t, SharingTokenReplayThrottle) for t in throttles)

    def test_non_sharing_requests_keep_default_throttles(self) -> None:
        viewset = self._viewset(action="retrieve", authenticator=PersonalAPIKeyAuthentication())

        throttles = viewset.get_throttles()

        assert not any(isinstance(t, SharingTokenReplayThrottle) for t in throttles)
