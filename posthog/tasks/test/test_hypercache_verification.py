"""
Tests for HyperCache verification Celery tasks.

Tests cover:
- Each task verifies its respective cache
- Errors are captured and re-raised
- Tasks skip when FLAGS_REDIS_URL not configured
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.storage.hypercache_verifier import TeamBatchFetchError, VerificationResult
from posthog.tasks.hypercache_verification import (
    DEADLINE_HEADROOM_SECONDS,
    verify_and_fix_flag_definitions_cache_task,
    verify_and_fix_flags_cache_task,
    verify_and_fix_team_metadata_cache_task,
)
from posthog.tasks.test.utils import PushGatewayTaskTestMixin
from posthog.tasks.utils import CeleryQueue


def _incomplete_runs(cache_type: str, reason: str) -> float:
    """Current value of the incomplete-runs counter in the default registry."""
    return (
        REGISTRY.get_sample_value(
            "posthog_hypercache_verification_incomplete_runs_total",
            {"cache_type": cache_type, "reason": reason},
        )
        or 0.0
    )


class TestFixCounterSeries(SimpleTestCase):
    def test_every_label_triple_is_pre_created_at_import(self) -> None:
        # Expectations are literals, not _FIX_WRITERS_BY_CACHE_TYPE: deriving them
        # from the dict would let a dropped writer (the rust series the ramp gates
        # on) shrink the test along with the code.
        for cache_type, writers in (
            ("flags", ("python", "rust", "unknown")),
            ("team_metadata", ("python",)),
            ("flag_definitions", ("python",)),
        ):
            for issue_type in ("cache_miss", "cache_mismatch", "expiry_missing"):
                for writer in writers:
                    assert (
                        REGISTRY.get_sample_value(
                            "posthog_hypercache_verify_fixes_total",
                            {"cache_type": cache_type, "issue_type": issue_type, "writer": writer},
                        )
                        is not None
                    ), f"series not pre-created: cache_type={cache_type}, issue_type={issue_type}, writer={writer}"


class TestIncompleteRunsCounterSeries(SimpleTestCase):
    def test_every_label_pair_is_pre_created_at_import(self) -> None:
        for cache_type in ("flags", "team_metadata", "flag_definitions"):
            for reason in ("db_unreachable", "error", "soft_time_limit", "deadline"):
                assert (
                    REGISTRY.get_sample_value(
                        "posthog_hypercache_verification_incomplete_runs_total",
                        {"cache_type": cache_type, "reason": reason},
                    )
                    is not None
                ), f"series not pre-created: cache_type={cache_type}, reason={reason}"


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixFlagsCacheTask(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_flags_cache(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = VerificationResult()

        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "flags"

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("flags verification failed")
        mock_run_verification.side_effect = error
        before = _incomplete_runs("flags", "error")

        with self.assertRaises(Exception) as context:
            verify_and_fix_flags_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error
        assert _incomplete_runs("flags", "error") == before + 1

    @parameterized.expand(
        [
            ("soft_time_limit", SoftTimeLimitExceeded()),
            ("db_unreachable", TeamBatchFetchError("db unreachable")),
        ]
    )
    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_wind_down_completes_cleanly_without_capturing(
        self, reason: str, error: Exception, mock_run_verification: MagicMock, mock_capture: MagicMock
    ) -> None:
        """A run that winds down early (time budget spent, or database unreachable after
        retries) is not captured as an error or re-raised, and the task's success metric
        reflects a clean finish."""
        mock_run_verification.side_effect = error
        before = _incomplete_runs("flags", reason)

        # Should not raise
        verify_and_fix_flags_cache_task()

        mock_capture.assert_not_called()
        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_flags_cache_task_success")
        assert success == 1
        assert _incomplete_runs("flags", reason) == before + 1

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_does_not_raise_when_succeeds(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = VerificationResult()

        # Should not raise
        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_called_once()

    @patch("posthog.tasks.hypercache_verification.time.monotonic", return_value=1000.0)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_passes_monotonic_deadline_to_sweep(
        self, mock_run_verification: MagicMock, _mock_monotonic: MagicMock
    ) -> None:
        # The sweep's wind-down deadline is the task's soft time limit minus the
        # headroom, so the batch-boundary check trips before Celery's soft-limit
        # signal can fire mid-batch.
        mock_run_verification.return_value = VerificationResult()

        verify_and_fix_flags_cache_task()

        expected = 1000.0 + (verify_and_fix_flags_cache_task.soft_time_limit - DEADLINE_HEADROOM_SECONDS)
        assert mock_run_verification.call_args.kwargs["stop_time"] == expected

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_deadline_winddown_records_incomplete_run_without_raising(self, mock_run_verification: MagicMock) -> None:
        # A deadline wind-down returns a partial result (no SoftTimeLimitExceeded raised);
        # it must still be counted as a "deadline" incomplete run, and finish cleanly.
        mock_run_verification.return_value = VerificationResult(wound_down_early=True)
        before = _incomplete_runs("flags", "deadline")

        # Should not raise
        verify_and_fix_flags_cache_task()

        assert _incomplete_runs("flags", "deadline") == before + 1
        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_flags_cache_task_success")
        assert success == 1

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_completed_sweep_does_not_record_incomplete_run(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = VerificationResult(wound_down_early=False)
        before = _incomplete_runs("flags", "deadline")

        verify_and_fix_flags_cache_task()

        assert _incomplete_runs("flags", "deadline") == before

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = VerificationResult()

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
        mock_run_verification.return_value = VerificationResult()

        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "team_metadata"

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("team_metadata verification failed")
        mock_run_verification.side_effect = error
        before = _incomplete_runs("team_metadata", "error")

        with self.assertRaises(Exception) as context:
            verify_and_fix_team_metadata_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error
        assert _incomplete_runs("team_metadata", "error") == before + 1

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_does_not_raise_when_succeeds(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = VerificationResult()

        # Should not raise
        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_called_once()

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = VerificationResult()

        verify_and_fix_team_metadata_cache_task()

        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_team_metadata_cache_task_success")
        duration = self.registry.get_sample_value(
            "posthog_celery_verify_and_fix_team_metadata_cache_task_duration_seconds"
        )
        assert success == 1
        assert duration is not None and duration >= 0

    def test_runs_on_feature_flags_long_running_queue(self) -> None:
        # Ensure the task is on FEATURE_FLAGS_LONG_RUNNING, not DEFAULT, to avoid
        # expiry-based starvation on the shared DEFAULT queue.
        assert verify_and_fix_team_metadata_cache_task.queue == CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value


@override_settings(FLAGS_REDIS_URL=None)
class TestVerifyAndFixTeamMetadataCacheTaskDisabled(TestCase):
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_skips_verification_when_no_redis_url(self, mock_run_verification: MagicMock) -> None:
        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_not_called()


class TestVerifyAndFixFlagDefinitionsCacheTask(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_verifies_flag_definitions_cache(self, mock_run_verification: MagicMock) -> None:
        from products.feature_flags.backend.local_evaluation import verify_team_flag_definitions

        mock_run_verification.return_value = VerificationResult()

        verify_and_fix_flag_definitions_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "flag_definitions"
        assert call_kwargs["verify_team_fn"] is verify_team_flag_definitions

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("flag_definitions verification failed")
        mock_run_verification.side_effect = error
        before = _incomplete_runs("flag_definitions", "error")

        with self.assertRaises(Exception) as context:
            verify_and_fix_flag_definitions_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.exception is error
        assert _incomplete_runs("flag_definitions", "error") == before + 1

    @parameterized.expand(
        [
            ("soft_time_limit", SoftTimeLimitExceeded()),
            ("db_unreachable", TeamBatchFetchError("db unreachable")),
        ]
    )
    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_wind_down_completes_cleanly_without_capturing(
        self, reason: str, error: Exception, mock_run_verification: MagicMock, mock_capture: MagicMock
    ) -> None:
        """A run that winds down early (time budget spent, or database unreachable after
        retries) is not captured as an error or re-raised, and the task's success metric
        reflects a clean finish."""
        mock_run_verification.side_effect = error
        before = _incomplete_runs("flag_definitions", reason)

        # Should not raise
        verify_and_fix_flag_definitions_cache_task()

        mock_capture.assert_not_called()
        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_flag_definitions_cache_task_success")
        assert success == 1
        assert _incomplete_runs("flag_definitions", reason) == before + 1

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_deadline_winddown_records_incomplete_run_without_raising(self, mock_run_verification: MagicMock) -> None:
        # flag_definitions runs through its own _run_flag_definitions_verification path,
        # so its deadline recording is wired separately from the flags/team_metadata path.
        mock_run_verification.return_value = VerificationResult(wound_down_early=True)
        before = _incomplete_runs("flag_definitions", "deadline")

        # Should not raise
        verify_and_fix_flag_definitions_cache_task()

        assert _incomplete_runs("flag_definitions", "deadline") == before + 1
        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_flag_definitions_cache_task_success")
        assert success == 1

    @patch("posthog.tasks.hypercache_verification.time.monotonic", return_value=1000.0)
    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_passes_monotonic_deadline_to_sweep(
        self, mock_run_verification: MagicMock, _mock_monotonic: MagicMock
    ) -> None:
        # The flag_definitions task threads its own soft time limit down as the deadline.
        mock_run_verification.return_value = VerificationResult()

        verify_and_fix_flag_definitions_cache_task()

        expected = 1000.0 + (verify_and_fix_flag_definitions_cache_task.soft_time_limit - DEADLINE_HEADROOM_SECONDS)
        assert mock_run_verification.call_args.kwargs["stop_time"] == expected

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_releases_lock_after_error(self, mock_run_verification: MagicMock) -> None:
        from django.core.cache import cache as django_cache

        mock_run_verification.side_effect = Exception("boom")

        with self.assertRaises(Exception):
            verify_and_fix_flag_definitions_cache_task()

        lock_key = "posthog:hypercache_verification:flag_definitions:lock"
        assert django_cache.add(lock_key, "test", timeout=1) is True
        django_cache.delete(lock_key)

    @patch("posthog.tasks.hypercache_verification._run_verification_for_cache")
    def test_pushgateway_metrics_recorded_on_success(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = VerificationResult()

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
