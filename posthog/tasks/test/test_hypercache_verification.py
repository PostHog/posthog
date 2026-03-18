"""
Tests for HyperCache verification Celery tasks.

Tests cover:
- Each task verifies its respective cache
- Errors are captured and re-raised
- Tasks skip when FLAGS_REDIS_URL not configured
"""

from collections.abc import Callable

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized

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


# Parameterized test configuration for the two flag definitions cache variants.
# Each tuple: (task_fn, include_cohorts, cache_type, other_cache_type, metric_name_fragment)
FLAG_DEFINITIONS_VARIANTS = [
    (
        "with_cohorts",
        verify_and_fix_flag_definitions_cache_task,
        True,
        "flag_definitions_with-cohorts",
        "flag_definitions_without-cohorts",
        "verify_and_fix_flag_definitions_cache_task",
    ),
    (
        "without_cohorts",
        verify_and_fix_flag_definitions_without_cohorts_cache_task,
        False,
        "flag_definitions_without-cohorts",
        "flag_definitions_with-cohorts",
        "verify_and_fix_flag_definitions_without_cohorts_cache_task",
    ),
]


class TestVerifyAndFixFlagDefinitionsCacheTask(PushGatewayTaskTestMixin, TestCase):
    """Tests for both flag definitions cache verification task variants."""

    @parameterized.expand(FLAG_DEFINITIONS_VARIANTS)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_correct_cache_type(
        self,
        _name: str,
        task_fn: Callable[[], None],
        _include_cohorts: bool,
        cache_type: str,
        _other: str,
        _metric: str,
        mock_run_verification: MagicMock,
    ) -> None:
        mock_run_verification.return_value = MagicMock()

        task_fn()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == cache_type

    @parameterized.expand(FLAG_DEFINITIONS_VARIANTS)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verify_fn_passes_correct_include_cohorts(
        self,
        _name: str,
        task_fn: Callable[[], None],
        include_cohorts: bool,
        _cache_type: str,
        _other: str,
        _metric: str,
        mock_run_verification: MagicMock,
    ) -> None:
        from posthog.models.feature_flag.local_evaluation import verify_team_flag_definitions

        mock_run_verification.return_value = MagicMock()

        task_fn()

        verify_fn = mock_run_verification.call_args[1]["verify_team_fn"]
        assert verify_fn.func is verify_team_flag_definitions
        assert verify_fn.keywords == {"include_cohorts": include_cohorts}

    @parameterized.expand(FLAG_DEFINITIONS_VARIANTS)
    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(
        self,
        _name: str,
        task_fn: Callable[[], None],
        _include_cohorts: bool,
        _cache_type: str,
        _other: str,
        _metric: str,
        mock_run_verification: MagicMock,
        mock_capture: MagicMock,
    ) -> None:
        error = Exception("flag_definitions verification failed")
        mock_run_verification.side_effect = error

        with self.assertRaises(Exception) as context:
            task_fn()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error

    @parameterized.expand(FLAG_DEFINITIONS_VARIANTS)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_releases_lock_after_error(
        self,
        _name: str,
        task_fn: Callable[[], None],
        _include_cohorts: bool,
        cache_type: str,
        _other: str,
        _metric: str,
        mock_run_verification: MagicMock,
    ) -> None:
        from django.core.cache import cache as django_cache

        mock_run_verification.side_effect = Exception("boom")

        with self.assertRaises(Exception):
            task_fn()

        lock_key = f"posthog:hypercache_verification:{cache_type}:lock"
        assert django_cache.add(lock_key, "test", timeout=1) is True
        django_cache.delete(lock_key)

    @parameterized.expand(FLAG_DEFINITIONS_VARIANTS)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_does_not_interfere_with_other_variant_lock(
        self,
        _name: str,
        task_fn: Callable[[], None],
        _include_cohorts: bool,
        _cache_type: str,
        other_cache_type: str,
        _metric: str,
        mock_run_verification: MagicMock,
    ) -> None:
        """Each variant uses its own lock key, so locking one doesn't block the other."""
        from django.core.cache import cache as django_cache

        other_lock_key = f"posthog:hypercache_verification:{other_cache_type}:lock"
        django_cache.add(other_lock_key, "locked", timeout=60)
        try:
            mock_run_verification.return_value = MagicMock()
            task_fn()
            mock_run_verification.assert_called_once()
        finally:
            django_cache.delete(other_lock_key)

    @parameterized.expand(FLAG_DEFINITIONS_VARIANTS)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(
        self,
        _name: str,
        task_fn: Callable[[], None],
        _include_cohorts: bool,
        _cache_type: str,
        _other: str,
        metric_name: str,
        mock_run_verification: MagicMock,
    ) -> None:
        mock_run_verification.return_value = MagicMock()

        task_fn()

        success = self.registry.get_sample_value(f"posthog_celery_{metric_name}_success")
        duration = self.registry.get_sample_value(f"posthog_celery_{metric_name}_duration_seconds")
        assert success == 1
        assert duration is not None and duration >= 0

    @parameterized.expand(FLAG_DEFINITIONS_VARIANTS)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_skips_when_lock_already_held(
        self,
        _name: str,
        task_fn: Callable[[], None],
        _include_cohorts: bool,
        cache_type: str,
        _other: str,
        _metric: str,
        mock_run_verification: MagicMock,
    ) -> None:
        from django.core.cache import cache as django_cache

        lock_key = f"posthog:hypercache_verification:{cache_type}:lock"
        django_cache.add(lock_key, "locked", timeout=60)
        try:
            task_fn()
            mock_run_verification.assert_not_called()
        finally:
            django_cache.delete(lock_key)
