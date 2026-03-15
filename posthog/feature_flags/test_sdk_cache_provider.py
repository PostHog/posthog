from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

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
