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
    verify_and_fix_flags_cache_task,
    verify_and_fix_team_metadata_cache_task,
)
import pytest


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixFlagsCacheTask(TestCase):
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_verifies_flags_cache(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "flags"

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("flags verification failed")
        mock_run_verification.side_effect = error

        with pytest.raises(Exception) as context:
            verify_and_fix_flags_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.value is error

    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_does_not_raise_when_succeeds(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        # Should not raise
        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_called_once()


@override_settings(FLAGS_REDIS_URL=None)
class TestVerifyAndFixFlagsCacheTaskDisabled(TestCase):
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_skips_verification_when_no_redis_url(self, mock_run_verification: MagicMock) -> None:
        verify_and_fix_flags_cache_task()

        mock_run_verification.assert_not_called()


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixTeamMetadataCacheTask(TestCase):
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_verifies_team_metadata_cache(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_called_once()
        call_kwargs = mock_run_verification.call_args[1]
        assert call_kwargs["cache_type"] == "team_metadata"

    @patch("posthog.tasks.hypercache_verification.capture_exception")
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_captures_and_reraises_error(self, mock_run_verification: MagicMock, mock_capture: MagicMock) -> None:
        error = Exception("team_metadata verification failed")
        mock_run_verification.side_effect = error

        with pytest.raises(Exception) as context:
            verify_and_fix_team_metadata_cache_task()

        mock_capture.assert_called_once_with(error)
        assert context.value is error

    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_does_not_raise_when_succeeds(self, mock_run_verification: MagicMock) -> None:
        mock_run_verification.return_value = MagicMock()

        # Should not raise
        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_called_once()


@override_settings(FLAGS_REDIS_URL=None)
class TestVerifyAndFixTeamMetadataCacheTaskDisabled(TestCase):
    @patch("posthog.storage.hypercache_verifier._run_verification_for_cache")
    def test_skips_verification_when_no_redis_url(self, mock_run_verification: MagicMock) -> None:
        verify_and_fix_team_metadata_cache_task()

        mock_run_verification.assert_not_called()
