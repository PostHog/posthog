from unittest.mock import patch

from django.test import SimpleTestCase

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

    @patch("posthog.models.feature_flag.local_evaluation.flag_definitions_hypercache")
    def test_get_flag_definitions_cache_hit(self, mock_hypercache):
        mock_hypercache.get_from_cache.return_value = {
            "flags": [{"key": "test-flag", "active": True}],
            "group_type_mapping": {"0": "company"},
            "cohorts": {"1": {"properties": []}},
        }

        result = self.provider.get_flag_definitions()

        assert result is not None
        assert result["flags"] == [{"key": "test-flag", "active": True}]
        assert result["group_type_mapping"] == {"0": "company"}
        assert result["cohorts"] == {"1": {"properties": []}}
        mock_hypercache.get_from_cache.assert_called_once_with(2)

    @patch("posthog.models.feature_flag.local_evaluation.flag_definitions_hypercache")
    def test_get_flag_definitions_cache_miss(self, mock_hypercache):
        mock_hypercache.get_from_cache.return_value = None

        result = self.provider.get_flag_definitions()

        assert result is None
        mock_hypercache.get_from_cache.assert_called_once_with(2)

    @patch("posthog.models.feature_flag.local_evaluation.flag_definitions_hypercache")
    def test_get_flag_definitions_exception_returns_none(self, mock_hypercache):
        mock_hypercache.get_from_cache.side_effect = Exception("Redis connection failed")

        result = self.provider.get_flag_definitions()

        assert result is None

    @patch("posthog.models.feature_flag.local_evaluation.flag_definitions_hypercache")
    def test_get_flag_definitions_handles_missing_keys(self, mock_hypercache):
        mock_hypercache.get_from_cache.return_value = {"flags": [{"key": "flag-1"}]}

        result = self.provider.get_flag_definitions()

        assert result is not None
        assert result["flags"] == [{"key": "flag-1"}]
        assert result["group_type_mapping"] == {}
        assert result["cohorts"] == {}

    def test_implements_protocol(self):
        from posthoganalytics.flag_definition_cache import FlagDefinitionCacheProvider

        assert isinstance(self.provider, FlagDefinitionCacheProvider)
