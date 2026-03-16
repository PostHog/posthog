"""
Tests for per-token auth cache invalidation tasks.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.tasks.team_access_cache_tasks import (
    invalidate_personal_api_key_cache_task,
    invalidate_secret_token_cache_task,
    invalidate_user_tokens_sync,
    invalidate_user_tokens_task,
)


class TestInvalidateSecretTokenCacheTask(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_secret_token_cache_task_success(self, mock_cache: MagicMock) -> None:
        result = invalidate_secret_token_cache_task(token_hash="sha256$abc123")

        mock_cache.invalidate_token.assert_called_once_with("sha256$abc123")
        assert result["status"] == "success"
        assert result["token_hash_prefix"] == "sha256$abc123"[:12]

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_secret_token_cache_task_failure_retries(self, mock_cache: MagicMock) -> None:
        mock_cache.invalidate_token.side_effect = Exception("Redis connection failed")

        with self.assertRaises(Exception):
            invalidate_secret_token_cache_task(token_hash="sha256$abc123")


class TestInvalidatePersonalApiKeyCacheTask(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_personal_api_key_cache_task_success(self, mock_cache: MagicMock) -> None:
        result = invalidate_personal_api_key_cache_task(secure_value="sha256$abc123", user_id=42)

        mock_cache.invalidate_token.assert_called_once_with("sha256$abc123")
        assert result["status"] == "success"

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_personal_api_key_cache_task_without_user_id(self, mock_cache: MagicMock) -> None:
        result = invalidate_personal_api_key_cache_task(secure_value="sha256$abc123")

        mock_cache.invalidate_token.assert_called_once_with("sha256$abc123")
        assert result["status"] == "success"

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_legacy_pbkdf2_key_falls_back_to_user_invalidation(self, mock_cache: MagicMock) -> None:
        result = invalidate_personal_api_key_cache_task(secure_value="pbkdf2_sha256$260000$salt$hash", user_id=42)

        mock_cache.invalidate_user_tokens.assert_called_once_with(42)
        mock_cache.invalidate_token.assert_not_called()
        assert result["status"] == "success"

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_legacy_pbkdf2_key_without_user_id_skips(self, mock_cache: MagicMock) -> None:
        # A legacy PBKDF2 key with no user_id cannot be invalidated: the cache uses SHA256
        # keys, so the PBKDF2 hash would never match. The task should skip with a warning.
        result = invalidate_personal_api_key_cache_task(secure_value="pbkdf2_sha256$260000$salt$hash")

        mock_cache.invalidate_token.assert_not_called()
        mock_cache.invalidate_user_tokens.assert_not_called()
        assert result["status"] == "skipped"
        assert result["reason"] == "legacy_key_no_user_id"

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_personal_api_key_cache_task_failure_retries(self, mock_cache: MagicMock) -> None:
        mock_cache.invalidate_token.side_effect = Exception("Redis connection failed")

        with self.assertRaises(Exception):
            invalidate_personal_api_key_cache_task(secure_value="sha256$abc123", user_id=42)


class TestInvalidateUserTokensTask(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_user_tokens_task_success(self, mock_cache: MagicMock) -> None:
        result = invalidate_user_tokens_task(user_id=42)

        mock_cache.invalidate_user_tokens.assert_called_once_with(42)
        assert result["status"] == "success"
        assert result["user_id"] == 42

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_user_tokens_task_failure_retries(self, mock_cache: MagicMock) -> None:
        mock_cache.invalidate_user_tokens.side_effect = Exception("Redis down")

        with self.assertRaises(Exception):
            invalidate_user_tokens_task(user_id=42)


class TestInvalidateUserTokensSync(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_user_tokens_sync_success(self, mock_cache: MagicMock) -> None:
        result = invalidate_user_tokens_sync(user_id=42)

        mock_cache.invalidate_user_tokens.assert_called_once_with(42)
        assert result["status"] == "success"
        assert result["user_id"] == 42

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_task")
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_user_tokens_sync_failure_schedules_async_retry(
        self, mock_cache: MagicMock, mock_task: MagicMock
    ) -> None:
        mock_cache.invalidate_user_tokens.side_effect = Exception("Redis down")

        result = invalidate_user_tokens_sync(user_id=42)

        self.assertEqual(result["status"], "failure")
        mock_task.apply_async.assert_called_once_with(args=[42], countdown=5)

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_task")
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_user_tokens_sync_handles_double_failure(
        self, mock_cache: MagicMock, mock_task: MagicMock
    ) -> None:
        mock_cache.invalidate_user_tokens.side_effect = Exception("Redis down")
        mock_task.apply_async.side_effect = Exception("Celery down too")

        result = invalidate_user_tokens_sync(user_id=42)

        self.assertEqual(result["status"], "failure")
