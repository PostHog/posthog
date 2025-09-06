"""
Tests for team access cache Celery tasks.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.tasks.team_access_cache_tasks import warm_all_team_access_caches_task, warm_team_cache_task


class TestWarmTeamCacheTask(TestCase):
    """Test the individual team cache warming task."""

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    def test_warm_team_cache_task_success(self, mock_warm: MagicMock) -> None:
        """Test successful cache warming for a team."""
        mock_warm.return_value = True

        project_api_key = "phs_test_team_123"

        result = warm_team_cache_task(project_api_key)

        mock_warm.assert_called_once_with(project_api_key)

        assert result["status"] == "success"
        assert result["project_api_key"] == project_api_key

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    def test_warm_team_cache_task_failure(self, mock_warm: MagicMock) -> None:
        """Test that cache warming failure does not trigger retry."""
        mock_warm.return_value = False

        project_api_key = "phs_test_team_123"

        result = warm_team_cache_task(project_api_key)

        mock_warm.assert_called_once_with(project_api_key)

        assert result["status"] == "failure"
        assert result["project_api_key"] == project_api_key


class TestWarmAllTeamsCachesTask(TestCase):
    """Test the batch cache warming task."""

    @patch("posthog.tasks.team_access_cache_tasks.get_teams_needing_cache_refresh_paginated")
    def test_warm_all_team_access_caches_task_no_teams(self, mock_get_teams_paginated: MagicMock) -> None:
        """Test batch warming when no teams need refresh."""
        mock_get_teams_paginated.return_value = iter([])

        result = warm_all_team_access_caches_task()

        assert result["status"] == "success"
        assert result["teams_found"] == 0
        assert result["teams_scheduled"] == 0
        assert result["failed_teams"] == 0

    @patch("posthog.tasks.team_access_cache_tasks.get_teams_needing_cache_refresh_paginated")
    @patch("posthog.tasks.team_access_cache_tasks.warm_team_cache_task.delay")
    @patch("posthog.tasks.team_access_cache_tasks.CACHE_WARMING_BATCH_SIZE", 2)
    def test_warm_all_team_access_caches_task_batching(
        self, mock_delay: MagicMock, mock_get_teams_paginated: MagicMock
    ) -> None:
        """Test that teams are processed in configured batches."""
        # Setup mock teams - more than batch size, split across pages
        page1 = ["phs_team1_123", "phs_team2_456"]
        page2 = ["phs_team3_789", "phs_team4_012"]
        mock_get_teams_paginated.return_value = iter([page1, page2])

        result = warm_all_team_access_caches_task()

        # Verify all teams were scheduled despite batching
        assert mock_delay.call_count == 4
        all_teams = page1 + page2
        for team in all_teams:
            mock_delay.assert_any_call(team)

        assert result["status"] == "success"
        assert result["teams_scheduled"] == 4
        assert result["teams_found"] == 4
        assert result["failed_teams"] == 0

    @patch("posthog.tasks.team_access_cache_tasks.get_teams_needing_cache_refresh_paginated")
    @patch("posthog.tasks.team_access_cache_tasks.warm_team_cache_task.delay")
    def test_warm_all_team_access_caches_task_handles_individual_failures(
        self, mock_delay: MagicMock, mock_get_teams_paginated: MagicMock
    ) -> None:
        """Test that batch warming handles individual team failures gracefully."""
        # Setup mocks - single page of teams
        mock_teams = ["phs_team1_123", "phs_team2_456", "phs_team3_789"]
        mock_get_teams_paginated.return_value = iter([mock_teams])

        # Make delay fail for the second team only
        def delay_side_effect(project_api_key: str) -> None:
            if project_api_key == "phs_team2_456":
                raise Exception("Task scheduling failed for team 2")
            return None

        mock_delay.side_effect = delay_side_effect

        # Execute task - should NOT raise exception, but should handle failure gracefully
        result = warm_all_team_access_caches_task()

        mock_get_teams_paginated.assert_called_once()

        # Verify all teams were attempted
        assert mock_delay.call_count == 3
        mock_delay.assert_any_call("phs_team1_123")
        mock_delay.assert_any_call("phs_team2_456")
        mock_delay.assert_any_call("phs_team3_789")

        # Verify result shows partial success
        assert result["status"] == "success"
        assert result["teams_scheduled"] == 2  # team2 failed to schedule
        assert result["failed_teams"] == 1
        assert result["teams_found"] == 3

    @patch("posthog.tasks.team_access_cache_tasks.get_teams_needing_cache_refresh_paginated")
    def test_warm_all_team_access_caches_task_handles_systemic_failures(
        self, mock_get_teams_paginated: MagicMock
    ) -> None:
        """Test that batch warming retries on systemic failures like database connectivity issues."""
        # Make get_teams_needing_cache_refresh_paginated fail (systemic issue)
        mock_get_teams_paginated.side_effect = Exception("Database connection failed")

        # Execute task - should raise some exception that triggers retry
        # The retry mechanism may raise the original exception or a Retry exception
        with self.assertRaises(Exception) as cm:
            warm_all_team_access_caches_task()

        mock_get_teams_paginated.assert_called_once()

        # Verify the exception is related to our test failure
        self.assertIn("Database connection failed", str(cm.exception))


class TestTaskIntegration(TestCase):
    """Integration tests for the complete task flow."""

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_needing_cache_refresh_paginated")
    def test_complete_cache_refresh_flow(self, mock_get_teams_paginated: MagicMock, mock_warm: MagicMock) -> None:
        """Test the complete flow from batch task to individual warming."""
        # Setup mocks - single page with one team
        mock_teams = ["phs_team1_123"]
        mock_get_teams_paginated.return_value = iter([mock_teams])
        mock_warm.return_value = True

        # Execute batch task (without actually scheduling async tasks)
        with patch("posthog.tasks.team_access_cache_tasks.warm_team_cache_task.delay") as mock_delay:
            batch_result = warm_all_team_access_caches_task()

            # Verify batch task scheduled individual task
            mock_delay.assert_called_once_with("phs_team1_123")

        # Simulate individual task execution
        individual_result = warm_team_cache_task("phs_team1_123")

        # Verify both tasks succeeded
        assert batch_result["status"] == "success"
        assert batch_result["teams_scheduled"] == 1
        assert batch_result["teams_found"] == 1
        assert batch_result["failed_teams"] == 0

        assert individual_result["status"] == "success"
        assert individual_result["project_api_key"] == "phs_team1_123"
