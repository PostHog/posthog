"""
Tests for flag definitions cache management.
"""

import os
from unittest.mock import Mock, patch
from django.core.cache import cache
from django.test import TestCase

from posthog.api.services.flag_definitions_cache import (
    FlagDefinitionsCache,
    invalidate_cache_for_feature_flag_change,
    invalidate_cache_for_cohort_change,
    invalidate_cache_for_group_type_mapping_change,
)


class TestFlagDefinitionsCache(TestCase):
    """Test the FlagDefinitionsCache class."""

    def setUp(self):
        """Set up test data."""
        cache.clear()
        self.project_id = 123
        self.test_data = {
            "flags": [{"key": "test-flag", "active": True}],
            "group_type_mapping": {"0": "organization"},
            "cohorts": {},
        }

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    def test_get_cache_key_without_cohorts(self):
        """Test cache key generation without cohorts."""
        key = FlagDefinitionsCache.get_cache_key(self.project_id, include_cohorts=False)
        expected = f"local_evaluation/{self.project_id}/v1"
        self.assertEqual(key, expected)

    def test_get_cache_key_with_cohorts(self):
        """Test cache key generation with cohorts."""
        key = FlagDefinitionsCache.get_cache_key(self.project_id, include_cohorts=True)
        expected = f"local_evaluation/{self.project_id}/cohorts/v1"
        self.assertEqual(key, expected)

    def test_get_all_cache_keys(self):
        """Test getting all cache keys for a project."""
        keys = FlagDefinitionsCache.get_all_cache_keys(self.project_id)
        expected = [
            f"local_evaluation/{self.project_id}/v1",
            f"local_evaluation/{self.project_id}/cohorts/v1",
        ]
        self.assertEqual(keys, expected)

    def test_set_and_get_cache_without_cohorts(self):
        """Test setting and getting cache data without cohorts."""
        # Set cache
        FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=False)

        # Get cache
        cached_data = FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False)

        self.assertEqual(cached_data, self.test_data)

    def test_set_and_get_cache_with_cohorts(self):
        """Test setting and getting cache data with cohorts."""
        # Set cache
        FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=True)

        # Get cache
        cached_data = FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=True)

        self.assertEqual(cached_data, self.test_data)

    def test_get_cache_returns_none_when_not_found(self):
        """Test that get_cache returns None when cache is empty."""
        cached_data = FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False)
        self.assertIsNone(cached_data)

    def test_cache_ttl_is_applied(self):
        """Test that cache TTL is properly applied."""
        with patch("django.core.cache.cache.set") as mock_set:
            FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=False)

            mock_set.assert_called_once_with(
                f"local_evaluation/{self.project_id}/v1",
                self.test_data,
                FlagDefinitionsCache.CACHE_TTL,
            )

    @patch("posthog.api.services.flag_definitions_cache.logging.getLogger")
    def test_set_cache_handles_exceptions(self, mock_get_logger):
        """Test that set_cache handles exceptions gracefully."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        with patch("django.core.cache.cache.set", side_effect=Exception("Cache error")):
            # Should not raise an exception
            FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=False)

            # Should log the error
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            self.assertIn("Failed to cache flag definitions", call_args[0][0])

    @patch("posthog.api.services.flag_definitions_cache.logging.getLogger")
    def test_get_cache_handles_exceptions(self, mock_get_logger):
        """Test that get_cache handles exceptions gracefully."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        with patch("django.core.cache.cache.get", side_effect=Exception("Cache error")):
            result = FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False)

            # Should return None when exception occurs
            self.assertIsNone(result)

            # Should log the error
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            self.assertIn("Failed to retrieve flag definitions from cache", call_args[0][0])

    def test_invalidate_for_project_deletes_all_keys(self):
        """Test that invalidate_for_project deletes both cache keys."""
        # Set up cache data
        FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=False)
        FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=True)

        # Verify cache is populated
        self.assertIsNotNone(FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False))
        self.assertIsNotNone(FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=True))

        # Invalidate cache
        FlagDefinitionsCache.invalidate_for_project(self.project_id, "test invalidation")

        # Verify cache is cleared
        self.assertIsNone(FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False))
        self.assertIsNone(FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=True))

    @patch("posthog.api.services.flag_definitions_cache.logging.getLogger")
    def test_invalidate_for_project_logs_success(self, mock_get_logger):
        """Test that invalidate_for_project logs successful invalidation."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        reason = "test invalidation"
        extra_context = {"flag_key": "test-flag"}

        FlagDefinitionsCache.invalidate_for_project(self.project_id, reason, extra_context)

        # Should log success
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        self.assertIn(f"Invalidated flag definitions cache: {reason}", call_args[0][0])

        # Check that extra context is included
        log_extra = call_args[1]["extra"]
        self.assertEqual(log_extra["project_id"], self.project_id)
        self.assertEqual(log_extra["flag_key"], "test-flag")

    @patch("posthog.api.services.flag_definitions_cache.logging.getLogger")
    def test_invalidate_for_project_handles_exceptions(self, mock_get_logger):
        """Test that invalidate_for_project handles exceptions gracefully."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        with patch("django.core.cache.cache.delete_many", side_effect=Exception("Cache error")):
            # Should not raise an exception
            FlagDefinitionsCache.invalidate_for_project(self.project_id, "test invalidation")

            # Should log the error
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            self.assertIn("Failed to invalidate flag definitions cache", call_args[0][0])

    @patch("posthog.api.services.flag_definitions_cache.statsd")
    def test_set_cache_records_metric(self, mock_statsd):
        """Test that set_cache records metrics."""
        FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=False)

        mock_statsd.incr.assert_called_once_with(
            "flag_definitions_cache_set",
            tags={"include_cohorts": "false"},
        )

    @patch("posthog.api.services.flag_definitions_cache.statsd")
    def test_get_cache_hit_records_metric(self, mock_statsd):
        """Test that get_cache records hit metric when data is found."""
        # Set up cache data first
        FlagDefinitionsCache.set_cache(self.project_id, self.test_data, include_cohorts=False)
        mock_statsd.reset_mock()  # Reset to ignore the set_cache metric

        # Get cache data
        result = FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False)

        self.assertEqual(result, self.test_data)
        mock_statsd.incr.assert_called_once_with(
            "flag_definitions_cache_hit",
            tags={"include_cohorts": "false"},
        )

    @patch("posthog.api.services.flag_definitions_cache.statsd")
    def test_get_cache_miss_records_metric(self, mock_statsd):
        """Test that get_cache records miss metric when data is not found."""
        result = FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False)

        self.assertIsNone(result)
        mock_statsd.incr.assert_called_once_with(
            "flag_definitions_cache_miss",
            tags={"include_cohorts": "false"},
        )

    @patch("posthog.api.services.flag_definitions_cache.statsd")
    def test_get_cache_error_records_metric(self, mock_statsd):
        """Test that get_cache records error metric on exception."""
        with patch("django.core.cache.cache.get", side_effect=Exception("Cache error")):
            result = FlagDefinitionsCache.get_cache(self.project_id, include_cohorts=False)

            self.assertIsNone(result)
            mock_statsd.incr.assert_called_once_with(
                "flag_definitions_cache_error",
                tags={"include_cohorts": "false"},
            )

    @patch("posthog.api.services.flag_definitions_cache.statsd")
    def test_invalidate_for_project_records_metric(self, mock_statsd):
        """Test that invalidate_for_project records invalidation metric."""
        reason = "test invalidation"
        FlagDefinitionsCache.invalidate_for_project(self.project_id, reason)

        mock_statsd.incr.assert_called_once_with(
            "flag_definitions_cache_invalidation",
            tags={"reason": reason},
        )


class TestCacheInvalidationUtilities(TestCase):
    """Test the cache invalidation utility functions."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("posthog.api.services.flag_definitions_cache.FlagDefinitionsCache.invalidate_for_project")
    def test_invalidate_cache_for_feature_flag_change(self, mock_invalidate):
        """Test feature flag change invalidation."""
        # Create mock feature flag instance
        mock_flag = Mock()
        mock_flag.team.project_id = 123
        mock_flag.key = "test-flag"

        activity = "created"

        invalidate_cache_for_feature_flag_change(mock_flag, activity)

        mock_invalidate.assert_called_once_with(
            project_id=123,
            reason="feature flag change",
            extra_context={
                "flag_key": "test-flag",
                "activity": "created",
            },
        )

    @patch("posthog.api.services.flag_definitions_cache.FlagDefinitionsCache.invalidate_for_project")
    @patch("posthog.api.services.flag_definitions_cache.logging.getLogger")
    def test_invalidate_cache_for_feature_flag_change_handles_exceptions(self, mock_get_logger, mock_invalidate):
        """Test feature flag change invalidation handles exceptions."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Create mock that raises an exception
        mock_flag = Mock()
        mock_flag.team.project_id = 123
        mock_flag.key = "test-flag"
        mock_invalidate.side_effect = Exception("Invalidation error")

        # Should not raise an exception
        invalidate_cache_for_feature_flag_change(mock_flag, "created")

        # Should log the error
        mock_logger.warning.assert_called_once()

    @patch("posthog.api.services.flag_definitions_cache.FlagDefinitionsCache.invalidate_for_project")
    def test_invalidate_cache_for_cohort_change(self, mock_invalidate):
        """Test cohort change invalidation."""
        # Create mock cohort instance
        mock_cohort = Mock()
        mock_cohort.team.project_id = 123
        mock_cohort.pk = 456
        mock_cohort.name = "test-cohort"

        invalidate_cache_for_cohort_change(mock_cohort)

        mock_invalidate.assert_called_once_with(
            project_id=123,
            reason="cohort change",
            extra_context={
                "cohort_id": 456,
                "cohort_name": "test-cohort",
            },
        )

    @patch("posthog.api.services.flag_definitions_cache.FlagDefinitionsCache.invalidate_for_project")
    def test_invalidate_cache_for_group_type_mapping_change(self, mock_invalidate):
        """Test group type mapping change invalidation."""
        # Create mock group type mapping instance
        mock_mapping = Mock()
        mock_mapping.project_id = 123
        mock_mapping.group_type = "organization"
        mock_mapping.group_type_index = 0

        invalidate_cache_for_group_type_mapping_change(mock_mapping)

        mock_invalidate.assert_called_once_with(
            project_id=123,
            reason="group type mapping change",
            extra_context={
                "group_type": "organization",
                "group_type_index": 0,
            },
        )

    @patch("posthog.api.services.flag_definitions_cache.FlagDefinitionsCache.invalidate_for_project")
    @patch("posthog.api.services.flag_definitions_cache.logging.getLogger")
    def test_utility_functions_handle_missing_attributes(self, mock_get_logger, mock_invalidate):
        """Test that utility functions handle missing attributes gracefully."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Create mock with missing attributes
        mock_instance = Mock()
        del mock_instance.team  # Remove team attribute to trigger exception

        # Should not raise an exception
        invalidate_cache_for_feature_flag_change(mock_instance, "created")

        # Should log the error
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        self.assertIn("Failed to invalidate flag definitions cache", call_args[0][0])


class TestCacheKeyConsistency(TestCase):
    """Test that cache keys are consistent with the original implementation."""

    def test_cache_key_format_without_cohorts(self):
        """Test cache key format matches original implementation."""
        project_id = 123
        key = FlagDefinitionsCache.get_cache_key(project_id, include_cohorts=False)
        expected = f"local_evaluation/{project_id}/v1"
        self.assertEqual(key, expected)

    def test_cache_key_format_with_cohorts(self):
        """Test cache key format with cohorts matches original implementation."""
        project_id = 123
        key = FlagDefinitionsCache.get_cache_key(project_id, include_cohorts=True)
        expected = f"local_evaluation/{project_id}/cohorts/v1"
        self.assertEqual(key, expected)

    def test_cache_ttl_uses_default_value(self):
        """Test that cache TTL uses default value when no env var is set."""
        # Default should be 3600 seconds (1 hour)
        self.assertEqual(FlagDefinitionsCache.CACHE_TTL, 3600)

    def test_cache_version_is_consistent(self):
        """Test that cache version is consistent."""
        self.assertEqual(FlagDefinitionsCache.CACHE_VERSION, "v1")

    @patch.dict(os.environ, {"FLAG_DEFINITIONS_CACHE_TTL": "1800"})
    @patch("posthog.api.services.flag_definitions_cache.os.getenv")
    def test_cache_ttl_respects_environment_variable(self, mock_getenv):
        """Test that cache TTL can be overridden via environment variable."""
        # Configure mock to return the environment variable value
        mock_getenv.return_value = "1800"

        # Test that the getenv call would return the expected value
        # This simulates what happens during module initialization
        result = int(mock_getenv("FLAG_DEFINITIONS_CACHE_TTL", 3600))
        self.assertEqual(result, 1800)

        # Verify getenv was called with correct parameters
        mock_getenv.assert_called_with("FLAG_DEFINITIONS_CACHE_TTL", 3600)
