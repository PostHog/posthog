from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from ee.hogai.sandbox_agent import FeatureNotEnabledError, SandboxAgentService, SandboxAgentTaskResult


class TestSpawnSandboxTask(BaseTest):
    @patch("ee.hogai.sandbox_agent.posthoganalytics")
    def test_raises_when_feature_not_enabled(self, mock_posthoganalytics):
        mock_posthoganalytics.feature_enabled.return_value = False

        with self.assertRaises(FeatureNotEnabledError):
            SandboxAgentService.spawn_sandbox_task(
                team=self.team,
                user=self.user,
                title="Fix bug",
                description="Fix the login bug",
                origin_product="user_created",
                repository="posthog/posthog-js",
            )

    @patch("ee.hogai.sandbox_agent.posthoganalytics")
    def test_creates_task_when_enabled(self, mock_posthoganalytics):
        mock_posthoganalytics.feature_enabled.return_value = True

        with patch("products.tasks.backend.models.Task.create_and_run") as mock_create_and_run:
            mock_task = MagicMock()
            mock_task.id = uuid4()
            mock_run = MagicMock()
            mock_run.id = uuid4()
            mock_task.latest_run = mock_run
            mock_create_and_run.return_value = mock_task

            result = SandboxAgentService.spawn_sandbox_task(
                team=self.team,
                user=self.user,
                title="Fix bug",
                description="Fix the login bug",
                origin_product="user_created",
                repository="posthog/posthog-js",
            )

            assert isinstance(result, SandboxAgentTaskResult)
            assert result.task_id == mock_task.id
            assert result.run_id == mock_run.id
            mock_create_and_run.assert_called_once()

    @patch("ee.hogai.sandbox_agent.posthoganalytics")
    def test_missing_github_integration_raises(self, mock_posthoganalytics):
        mock_posthoganalytics.feature_enabled.return_value = True

        with self.assertRaises(ValueError, msg="does not have a GitHub integration"):
            SandboxAgentService.spawn_sandbox_task(
                team=self.team,
                user=self.user,
                title="Fix bug",
                description="Fix the login bug",
                origin_product="user_created",
                repository="posthog/posthog-js",
            )
