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
    """Tests for the flag definitions cache verification task."""

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_both_flag_definitions_variants(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flag_definitions_cache_task()

        assert mock_run_verification.call_count == 2
        cache_types = [call[1]["cache_type"] for call in mock_run_verification.call_args_list]
        assert cache_types == ["flag_definitions_with-cohorts", "flag_definitions_without-cohorts"]

    @patch("posthog.tasks.hypercache_verification.verify_team_flag_definitions")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_each_variant_captures_correct_include_cohorts(
        self, mock_run_verification: MagicMock, mock_verify_team: MagicMock
    ) -> None:
        """Guard against the closure-in-loop bug: each verify_fn must capture its own include_cohorts value."""
        mock_run_verification.return_value = MagicMock()
        mock_verify_team.return_value = {"status": "match", "issue": None}

        verify_and_fix_flag_definitions_cache_task()

        verify_fn_with = mock_run_verification.call_args_list[0][1]["verify_team_fn"]
        verify_fn_without = mock_run_verification.call_args_list[1][1]["verify_team_fn"]

        mock_team = MagicMock()
        verify_fn_with(mock_team)
        mock_verify_team.assert_called_with(
            mock_team, db_batch_data=None, cache_batch_data=None, include_cohorts=True, verbose=False
        )

        mock_verify_team.reset_mock()
        verify_fn_without(mock_team)
        mock_verify_team.assert_called_with(
            mock_team, db_batch_data=None, cache_batch_data=None, include_cohorts=False, verbose=False
        )

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_error_continues_to_next_variant_then_reraises(
        self, mock_run_verification: MagicMock, mock_capture: MagicMock
    ) -> None:
        error = Exception("flag_definitions verification failed")
        mock_run_verification.side_effect = [error, MagicMock()]

        with self.assertRaises(Exception) as context:
            verify_and_fix_flag_definitions_cache_task()

        assert context.exception is error
        mock_capture.assert_called_once_with(error)
        assert mock_run_verification.call_count == 2

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_both_variants_fail_captures_both_reraises_first(
        self, mock_run_verification: MagicMock, mock_capture: MagicMock
    ) -> None:
        error1 = Exception("with-cohorts failed")
        error2 = Exception("without-cohorts failed")
        mock_run_verification.side_effect = [error1, error2]

        with self.assertRaises(Exception) as context:
            verify_and_fix_flag_definitions_cache_task()

        assert context.exception is error1
        assert mock_capture.call_count == 2
        mock_capture.assert_any_call(error1)
        mock_capture.assert_any_call(error2)

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

        lock_key = "posthog:hypercache_verification:flag_definitions:lock"
        django_cache.add(lock_key, "locked", timeout=60)
        try:
            verify_and_fix_flag_definitions_cache_task()
            mock_run_verification.assert_not_called()
        finally:
            django_cache.delete(lock_key)
