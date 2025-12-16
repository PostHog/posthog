"""
Tests for HyperCache verification Celery task.

Tests cover:
- Task continues to second cache if first fails
- Errors are captured and re-raised
- Task skips when FLAGS_REDIS_URL not configured
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from posthog.tasks.hypercache_verification import verify_and_fix_hypercaches_task


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixHypercachesTask(TestCase):
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_verifies_both_caches(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_hypercaches_task()

        # Should be called twice - once for each cache type
        assert mock_run_verification.call_count == 2

        # Verify cache types
        call_args = [call[1]["cache_type"] for call in mock_run_verification.call_args_list]
        assert "team_metadata" in call_args
        assert "flags" in call_args

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_continues_to_second_cache_if_first_fails(
        self, mock_run_verification: MagicMock, mock_capture: MagicMock
    ) -> None:
        # First call raises, second succeeds
        mock_run_verification.side_effect = [
            Exception("team_metadata verification failed"),
            MagicMock(),
        ]

        with self.assertRaises(Exception) as context:
            verify_and_fix_hypercaches_task()

        # Should still call both caches
        assert mock_run_verification.call_count == 2

        # Error should be captured
        mock_capture.assert_called_once()

        # Should re-raise the first error
        assert "team_metadata verification failed" in str(context.exception)

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_captures_and_reraises_first_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        first_error = Exception("first error")
        second_error = Exception("second error")
        mock_run_verification.side_effect = [first_error, second_error]

        with self.assertRaises(Exception) as context:
            verify_and_fix_hypercaches_task()

        # Both errors should be captured
        assert mock_capture.call_count == 2

        # First error should be re-raised
        assert context.exception is first_error

    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_does_not_raise_when_both_succeed(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        # Should not raise
        verify_and_fix_hypercaches_task()

        assert mock_run_verification.call_count == 2


@override_settings(FLAGS_REDIS_URL=None)
class TestVerifyAndFixHypercachesTaskDisabled(TestCase):
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_skips_verification_when_no_redis_url(self, mock_run_verification: MagicMock) -> None:
        verify_and_fix_hypercaches_task()

        # Should not call verification at all
        mock_run_verification.assert_not_called()
