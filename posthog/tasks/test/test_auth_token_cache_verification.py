from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from posthog.storage.auth_token_cache_verifier import AuthTokenVerificationResult
from posthog.tasks.auth_token_cache_verification import LOCK_KEY, verify_and_fix_auth_token_cache_task
from posthog.tasks.test.utils import PushGatewayTaskTestMixin


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyAndFixAuthTokenCacheTask(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.storage.auth_token_cache_verifier.verify_and_fix_auth_token_cache")
    @patch("posthog.redis.get_client")
    def test_runs_verification(self, mock_get_client: MagicMock, mock_verify: MagicMock) -> None:
        mock_verify.return_value = AuthTokenVerificationResult()

        verify_and_fix_auth_token_cache_task()

        mock_verify.assert_called_once()

    @patch("posthog.tasks.auth_token_cache_verification.capture_exception")
    @patch("posthog.storage.auth_token_cache_verifier.verify_and_fix_auth_token_cache")
    @patch("posthog.redis.get_client")
    def test_captures_and_reraises_error(
        self, mock_get_client: MagicMock, mock_verify: MagicMock, mock_capture: MagicMock
    ) -> None:
        error = Exception("verification failed")
        mock_verify.side_effect = error

        with self.assertRaises(Exception) as context:
            verify_and_fix_auth_token_cache_task()

        assert context.exception is error
        mock_capture.assert_called_once_with(error)

    @patch("posthog.storage.auth_token_cache_verifier.verify_and_fix_auth_token_cache")
    @patch("posthog.redis.get_client")
    def test_pushgateway_metrics_recorded(self, mock_get_client: MagicMock, mock_verify: MagicMock) -> None:
        mock_verify.return_value = AuthTokenVerificationResult()

        verify_and_fix_auth_token_cache_task()

        success = self.registry.get_sample_value("posthog_celery_verify_and_fix_auth_token_cache_task_success")
        duration = self.registry.get_sample_value(
            "posthog_celery_verify_and_fix_auth_token_cache_task_duration_seconds"
        )
        assert success == 1
        assert duration is not None and duration >= 0

    @patch("posthog.storage.auth_token_cache_verifier.verify_and_fix_auth_token_cache")
    @patch("posthog.redis.get_client")
    @patch("posthog.tasks.auth_token_cache_verification.django_cache")
    def test_skips_when_lock_held(
        self, mock_cache: MagicMock, mock_get_client: MagicMock, mock_verify: MagicMock
    ) -> None:
        mock_cache.add.return_value = False

        verify_and_fix_auth_token_cache_task()

        mock_get_client.assert_not_called()
        mock_verify.assert_not_called()

    @patch("posthog.tasks.auth_token_cache_verification.capture_exception")
    @patch("posthog.storage.auth_token_cache_verifier.verify_and_fix_auth_token_cache")
    @patch("posthog.redis.get_client")
    @patch("posthog.tasks.auth_token_cache_verification.django_cache")
    def test_releases_lock_on_error(
        self, mock_cache: MagicMock, mock_get_client: MagicMock, mock_verify: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_cache.add.return_value = True
        mock_verify.side_effect = Exception("verification failed")

        with self.assertRaises(Exception):
            verify_and_fix_auth_token_cache_task()

        mock_cache.delete.assert_called_once_with(LOCK_KEY)

    @patch("posthog.storage.auth_token_cache_verifier.verify_and_fix_auth_token_cache")
    @patch("posthog.redis.get_client")
    @patch("posthog.tasks.auth_token_cache_verification.django_cache")
    def test_releases_lock_on_success(
        self, mock_cache: MagicMock, mock_get_client: MagicMock, mock_verify: MagicMock
    ) -> None:
        mock_cache.add.return_value = True
        mock_verify.return_value = AuthTokenVerificationResult()

        verify_and_fix_auth_token_cache_task()

        mock_cache.delete.assert_called_once_with(LOCK_KEY)


@override_settings(FLAGS_REDIS_URL=None)
class TestVerifyAndFixAuthTokenCacheTaskDisabled(TestCase):
    @patch("posthog.redis.get_client")
    def test_skips_when_no_redis_url(self, mock_get_client: MagicMock) -> None:
        verify_and_fix_auth_token_cache_task()

        mock_get_client.assert_not_called()
