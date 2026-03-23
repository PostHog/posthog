from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.tasks.team_access_cache_tasks import (
    invalidate_token_cache_task,
    invalidate_token_sync,
    invalidate_user_tokens_sync,
    invalidate_user_tokens_task,
)


class TestInvalidateTokenCacheTask(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_token_cache_task_success(self, mock_cache: MagicMock) -> None:
        result = invalidate_token_cache_task(token_hash="sha256$abc123")

        mock_cache.invalidate_token.assert_called_once_with("sha256$abc123")
        assert result["status"] == "success"
        assert result["token_prefix"] == "sha256$abc12"

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_token_cache_task_failure_raises(self, mock_cache: MagicMock) -> None:
        mock_cache.invalidate_token.side_effect = Exception("Redis connection failed")

        with self.assertRaises(Exception):
            invalidate_token_cache_task(token_hash="sha256$abc123")


class TestInvalidateUserTokensTask(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_user_tokens_task_success(self, mock_cache: MagicMock) -> None:
        result = invalidate_user_tokens_task(user_id=42)

        mock_cache.invalidate_user_tokens.assert_called_once_with(42)
        assert result["status"] == "success"
        assert result["user_id"] == 42

    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_user_tokens_task_failure_raises(self, mock_cache: MagicMock) -> None:
        mock_cache.invalidate_user_tokens.side_effect = Exception("Redis down")

        with self.assertRaises(Exception):
            invalidate_user_tokens_task(user_id=42)


class TestInvalidateTokenSync(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_token_sync_success(self, mock_cache: MagicMock) -> None:
        result = invalidate_token_sync(token_hash="sha256$abc123")

        mock_cache.invalidate_token.assert_called_once_with("sha256$abc123")
        assert result["status"] == "success"
        assert result["token_prefix"] == "sha256$abc12"

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_cache_task")
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_token_sync_failure_schedules_async_retry(
        self, mock_cache: MagicMock, mock_task: MagicMock
    ) -> None:
        mock_cache.invalidate_token.side_effect = Exception("Redis down")

        result = invalidate_token_sync(token_hash="sha256$abc123")

        self.assertEqual(result["status"], "failure")
        mock_task.apply_async.assert_called_once_with(args=["sha256$abc123"], countdown=5)

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_cache_task")
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    def test_invalidate_token_sync_handles_double_failure(self, mock_cache: MagicMock, mock_task: MagicMock) -> None:
        mock_cache.invalidate_token.side_effect = Exception("Redis down")
        mock_task.apply_async.side_effect = Exception("Celery down too")

        result = invalidate_token_sync(token_hash="sha256$abc123")

        self.assertEqual(result["status"], "failure")


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
