from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.client import Client

from posthog.feature_flags.sdk_cache_provider import HyperCacheFlagProvider


class TestHyperCacheFlagProvider(SimpleTestCase):
    def setUp(self):
        self.provider = HyperCacheFlagProvider(team_id=2)

    def test_should_fetch_flag_definitions_always_returns_false(self):
        assert self.provider.should_fetch_flag_definitions() is False

    def test_on_flag_definitions_received_is_noop(self):
        self.provider.on_flag_definitions_received({"flags": [], "group_type_mapping": {}, "cohorts": {}})

    def test_shutdown_is_noop(self):
        self.provider.shutdown()

    @parameterized.expand(
        [
            (
                "cache_hit",
                {
                    "flags": [{"key": "test-flag", "active": True}],
                    "group_type_mapping": {"0": "company"},
                    "cohorts": {"1": {"properties": []}},
                },
                None,
                {
                    "flags": [{"key": "test-flag", "active": True}],
                    "group_type_mapping": {"0": "company"},
                    "cohorts": {"1": {"properties": []}},
                },
            ),
            ("cache_miss", None, None, None),
            (
                "missing_keys_defaults",
                {"flags": [{"key": "flag-1"}]},
                None,
                {"flags": [{"key": "flag-1"}], "group_type_mapping": {}, "cohorts": {}},
            ),
            ("exception", None, Exception("Redis connection failed"), None),
        ]
    )
    @patch("posthog.models.feature_flag.local_evaluation.flag_definitions_hypercache")
    def test_get_flag_definitions(self, _name, cache_return, side_effect, expected, mock_hypercache):
        # Reset cached reference so the mock is picked up
        self.provider._hypercache = None

        if side_effect:
            mock_hypercache.get_from_cache.side_effect = side_effect
        else:
            mock_hypercache.get_from_cache.return_value = cache_return

        result = self.provider.get_flag_definitions()

        if expected is None:
            assert result is None
        else:
            assert result == expected

    @patch(
        "posthog.feature_flags.sdk_cache_provider.HyperCacheFlagProvider._get_hypercache",
        side_effect=ImportError("circular import"),
    )
    def test_get_flag_definitions_returns_none_on_circular_import(self, _mock):
        assert self.provider.get_flag_definitions() is None

    @patch("posthog.models.feature_flag.local_evaluation.flag_definitions_hypercache")
    def test_caches_hypercache_reference(self, mock_hypercache):
        self.provider._hypercache = None
        mock_hypercache.get_from_cache.return_value = None

        self.provider.get_flag_definitions()
        self.provider.get_flag_definitions()

        assert self.provider._hypercache is not None

    def test_implements_protocol(self):
        from posthoganalytics.flag_definition_cache import FlagDefinitionCacheProvider

        assert isinstance(self.provider, FlagDefinitionCacheProvider)


SAMPLE_FLAGS = {
    "flags": [
        {"id": 1, "key": "beta-feature", "active": True, "filters": {"groups": [{"rollout_percentage": 100}]}},
        {"id": 2, "key": "disabled-flag", "active": False, "filters": {}},
    ],
    "group_type_mapping": {"0": "company", "1": "project"},
    "cohorts": {"10": {"properties": [{"key": "plan", "value": "enterprise"}]}},
}


class TestSDKClientIntegration(SimpleTestCase):
    """Test HyperCacheFlagProvider with a real posthoganalytics.Client."""

    def _make_client(self, provider: HyperCacheFlagProvider) -> Client:
        return Client(
            project_api_key="test-key",
            personal_api_key="test-personal-key",
            host="http://localhost:8000",
            flag_definition_cache_provider=provider,
            poll_interval=99999,  # prevent background polling
            send=False,
            enable_exception_autocapture=False,
        )

    def test_sdk_loads_flags_from_provider_instead_of_api(self):
        mock_hypercache = MagicMock()
        mock_hypercache.get_from_cache.return_value = SAMPLE_FLAGS
        provider = HyperCacheFlagProvider(team_id=2)
        provider._hypercache = mock_hypercache

        client = self._make_client(provider)

        with patch.object(client, "_fetch_feature_flags_from_api") as mock_api:
            client._load_feature_flags()

            mock_api.assert_not_called()

        assert len(client.feature_flags) == 2
        flags_by_key: dict = client.feature_flags_by_key or {}
        assert flags_by_key["beta-feature"]["active"] is True
        assert client.group_type_mapping == {"0": "company", "1": "project"}
        assert client.cohorts == {"10": {"properties": [{"key": "plan", "value": "enterprise"}]}}

    def test_sdk_falls_back_to_api_when_cache_is_empty_and_no_flags_loaded(self):
        mock_hypercache = MagicMock()
        mock_hypercache.get_from_cache.return_value = None
        provider = HyperCacheFlagProvider(team_id=2)
        provider._hypercache = mock_hypercache

        client = self._make_client(provider)

        with patch.object(client, "_fetch_feature_flags_from_api") as mock_api:
            client._load_feature_flags()

            mock_api.assert_called_once()

    def test_sdk_skips_api_when_cache_empty_but_flags_already_loaded(self):
        mock_hypercache = MagicMock()
        provider = HyperCacheFlagProvider(team_id=2)
        provider._hypercache = mock_hypercache

        client = self._make_client(provider)

        # First call: cache has data → loads flags
        mock_hypercache.get_from_cache.return_value = SAMPLE_FLAGS
        client._load_feature_flags()
        assert len(client.feature_flags) == 2

        # Second call: cache is empty → keeps existing flags, no API call
        mock_hypercache.get_from_cache.return_value = None

        with patch.object(client, "_fetch_feature_flags_from_api") as mock_api:
            client._load_feature_flags()

            mock_api.assert_not_called()

        # Flags from the first load are still there
        assert len(client.feature_flags) == 2

    def test_sdk_picks_up_flag_changes_on_next_poll(self):
        mock_hypercache = MagicMock()
        provider = HyperCacheFlagProvider(team_id=2)
        provider._hypercache = mock_hypercache

        client = self._make_client(provider)

        # Initial load
        mock_hypercache.get_from_cache.return_value = SAMPLE_FLAGS
        client._load_feature_flags()
        flags_by_key: dict = client.feature_flags_by_key or {}
        assert flags_by_key["beta-feature"]["active"] is True

        # Flag changed in HyperCache (e.g., toggled off via Django admin)
        updated_flags = {
            "flags": [
                {"id": 1, "key": "beta-feature", "active": False, "filters": {}},
            ],
            "group_type_mapping": {},
            "cohorts": {},
        }
        mock_hypercache.get_from_cache.return_value = updated_flags
        client._load_feature_flags()

        flags_by_key = client.feature_flags_by_key or {}
        assert flags_by_key["beta-feature"]["active"] is False
        assert len(client.feature_flags) == 1

    def test_sdk_falls_back_to_api_when_provider_raises(self):
        mock_hypercache = MagicMock()
        mock_hypercache.get_from_cache.side_effect = Exception("Redis down")
        provider = HyperCacheFlagProvider(team_id=2)
        provider._hypercache = mock_hypercache

        client = self._make_client(provider)

        with patch.object(client, "_fetch_feature_flags_from_api") as mock_api:
            client._load_feature_flags()

            mock_api.assert_called_once()
