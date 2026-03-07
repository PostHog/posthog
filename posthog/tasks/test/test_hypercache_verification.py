"""
Tests for HyperCache verification Celery tasks.

Tests cover:
- Each task verifies its respective cache
- Errors are captured and re-raised
- Tasks skip when FLAGS_REDIS_URL not configured
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from posthog.tasks.hypercache_verification import (
    verify_and_fix_flag_definitions_cache_task,
    verify_and_fix_flag_definitions_without_cohorts_cache_task,
    verify_and_fix_flags_cache_task,
    verify_and_fix_team_metadata_cache_task,
)
from posthog.tasks.test.utils import PushGatewayTaskTestMixin


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixFlagsCacheTask(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_flags_cache(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "flags"

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("flags verification failed")
        mock_run_verification.side_effect = error

        with self.assertRaises(Exception) as context:
            verify_and_fix_flags_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_does_not_raise_when_succeeds(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        # Should not raise
        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_called_once()

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flags_cache_task()

        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_flags_cache_task_success")
        duration = self.registry.get_sample_value("posthog_celery_verify_and_fix_flags_cache_task_duration_seconds")
        assert success == 1
        assert duration is not None and duration >= 0


@override_settings(FLAGS_REDIS_URL=None)
class TestVerifyAndFixFlagsCacheTaskDisabled(TestCase):
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_skips_verification_when_no_redis_url(self, mock_run_verification: MagicMock) -> None:
        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_not_called()


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixTeamMetadataCacheTask(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_team_metadata_cache(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "team_metadata"

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("team_metadata verification failed")
        mock_run_verification.side_effect = error

        with self.assertRaises(Exception) as context:
            verify_and_fix_team_metadata_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_does_not_raise_when_succeeds(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        # Should not raise
        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_called_once()

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_team_metadata_cache_task()

        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_team_metadata_cache_task_success")
        duration = self.registry.get_sample_value(
            "posthog_celery_verify_and_fix_team_metadata_cache_task_duration_seconds"
        )
        assert success == 1
        assert duration is not None and duration >= 0


@override_settings(FLAGS_REDIS_URL=None)
class TestVerifyAndFixTeamMetadataCacheTaskDisabled(TestCase):
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_skips_verification_when_no_redis_url(self, mock_run_verification: MagicMock) -> None:
        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_not_called()


class TestVerifyAndFixFlagDefinitionsCacheTask(PushGatewayTaskTestMixin, TestCase):
    """Tests for the flag definitions (with-cohorts) cache verification task."""

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_with_cohorts_variant(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flag_definitions_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "flag_definitions_with-cohorts"

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verify_fn_passes_include_cohorts_true(self, mock_run_verification: MagicMock) -> None:
        from posthog.models.feature_flag.local_evaluation import verify_team_flag_definitions

        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flag_definitions_cache_task()

        verify_fn = mock_run_verification.call_args[1]["verify_team_fn"]
        assert verify_fn.func is verify_team_flag_definitions
        assert verify_fn.keywords == {"include_cohorts": True}

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("flag_definitions verification failed")
        mock_run_verification.side_effect = error

        with self.assertRaises(Exception) as context:
            verify_and_fix_flag_definitions_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_releases_lock_after_error(self, mock_run_verification: MagicMock) -> None:
        from django.core.cache import cache as django_cache

        mock_run_verification.side_effect = Exception("boom")

        with self.assertRaises(Exception):
            verify_and_fix_flag_definitions_cache_task()

        lock_key = "posthog:hypercache_verification:flag_definitions_with-cohorts:lock"
        assert django_cache.add(lock_key, "test", timeout=1) is True
        django_cache.delete(lock_key)

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_does_not_interfere_with_without_cohorts_lock(self, mock_run_verification: MagicMock) -> None:
        """Each variant uses its own lock key, so locking one doesn't block the other."""
        from django.core.cache import cache as django_cache

        other_lock_key = "posthog:hypercache_verification:flag_definitions_without-cohorts:lock"
        django_cache.add(other_lock_key, "locked", timeout=60)
        try:
            mock_run_verification.return_value = MagicMock()
            verify_and_fix_flag_definitions_cache_task()
            mock_run_verification.assert_called_once()
        finally:
            django_cache.delete(other_lock_key)

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flag_definitions_cache_task()

        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_flag_definitions_cache_task_success")
        duration = self.registry.get_sample_value(
            "posthog_celery_verify_and_fix_flag_definitions_cache_task_duration_seconds"
        )
        assert success == 1
        assert duration is not None and duration >= 0

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_skips_when_lock_already_held(self, mock_run_verification: MagicMock) -> None:
        from django.core.cache import cache as django_cache

        lock_key = "posthog:hypercache_verification:flag_definitions_with-cohorts:lock"
        django_cache.add(lock_key, "locked", timeout=60)
        try:
            verify_and_fix_flag_definitions_cache_task()
            mock_run_verification.assert_not_called()
        finally:
            django_cache.delete(lock_key)


class TestVerifyAndFixFlagDefinitionsWithoutCohortsCacheTask(PushGatewayTaskTestMixin, TestCase):
    """Tests for the flag definitions (without-cohorts) cache verification task."""

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_without_cohorts_variant(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flag_definitions_without_cohorts_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "flag_definitions_without-cohorts"

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verify_fn_passes_include_cohorts_false(self, mock_run_verification: MagicMock) -> None:
        from posthog.models.feature_flag.local_evaluation import verify_team_flag_definitions

        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flag_definitions_without_cohorts_cache_task()

        verify_fn = mock_run_verification.call_args[1]["verify_team_fn"]
        assert verify_fn.func is verify_team_flag_definitions
        assert verify_fn.keywords == {"include_cohorts": False}

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("flag_definitions verification failed")
        mock_run_verification.side_effect = error

        with self.assertRaises(Exception) as context:
            verify_and_fix_flag_definitions_without_cohorts_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_releases_lock_after_error(self, mock_run_verification: MagicMock) -> None:
        from django.core.cache import cache as django_cache

        mock_run_verification.side_effect = Exception("boom")

        with self.assertRaises(Exception):
            verify_and_fix_flag_definitions_without_cohorts_cache_task()

        lock_key = "posthog:hypercache_verification:flag_definitions_without-cohorts:lock"
        assert django_cache.add(lock_key, "test", timeout=1) is True
        django_cache.delete(lock_key)

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flag_definitions_without_cohorts_cache_task()

        success = self.registry.get_sample_value(
            "posthog_celery_verify_and_fix_flag_definitions_without_cohorts_cache_task_success"
        )
        duration = self.registry.get_sample_value(
            "posthog_celery_verify_and_fix_flag_definitions_without_cohorts_cache_task_duration_seconds"
        )
        assert success == 1
        assert duration is not None and duration >= 0

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_skips_when_lock_already_held(self, mock_run_verification: MagicMock) -> None:
        from django.core.cache import cache as django_cache

        lock_key = "posthog:hypercache_verification:flag_definitions_without-cohorts:lock"
        django_cache.add(lock_key, "locked", timeout=60)
        try:
            verify_and_fix_flag_definitions_without_cohorts_cache_task()
            mock_run_verification.assert_not_called()
        finally:
            django_cache.delete(lock_key)

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_does_not_interfere_with_with_cohorts_lock(self, mock_run_verification: MagicMock) -> None:
        """Each variant uses its own lock key, so locking one doesn't block the other."""
        from django.core.cache import cache as django_cache

        other_lock_key = "posthog:hypercache_verification:flag_definitions_with-cohorts:lock"
        django_cache.add(other_lock_key, "locked", timeout=60)
        try:
            mock_run_verification.return_value = MagicMock()
            verify_and_fix_flag_definitions_without_cohorts_cache_task()
            mock_run_verification.assert_called_once()
        finally:
            django_cache.delete(other_lock_key)
