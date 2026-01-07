"""
Tests for team access cache Celery tasks.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.tasks.team_access_cache_tasks import (
    warm_all_team_access_caches_task,
    warm_organization_teams_cache_task,
    warm_personal_api_key_deleted_cache_task,
    warm_personal_api_key_teams_cache_task,
    warm_team_cache_task,
    warm_user_teams_cache_sync,
    warm_user_teams_cache_task,
)
import pytest


class TestWarmUserTeamsCacheSync(TestCase):
    """Test the synchronous user teams cache warming function (used for deactivation)."""

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_user_teams_cache_sync_success(self, mock_get_teams: MagicMock, mock_warm: MagicMock) -> None:
        """Test successful synchronous cache warming for user deactivation."""
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        result = warm_user_teams_cache_sync(user_id=42)

        mock_get_teams.assert_called_once_with(42)
        assert mock_warm.call_count == 2
        mock_warm.assert_any_call("phs_team1_123")
        mock_warm.assert_any_call("phs_team2_456")

        assert result["status"] == "success"
        assert result["user_id"] == 42
        assert result["teams_updated"] == 2

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_user_teams_cache_sync_no_teams(self, mock_get_teams: MagicMock, mock_warm: MagicMock) -> None:
        """Test synchronous cache warming when user has no teams."""
        mock_get_teams.return_value = []

        result = warm_user_teams_cache_sync(user_id=42)

        mock_get_teams.assert_called_once_with(42)
        mock_warm.assert_not_called()

        assert result["status"] == "success"
        assert result["user_id"] == 42
        assert result["teams_updated"] == 0


class TestWarmUserTeamsCacheTask(TestCase):
    """Test the user teams cache warming task (async, used for activation)."""

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_user_teams_cache_task_success(self, mock_get_teams: MagicMock, mock_warm: MagicMock) -> None:
        """Test successful cache warming for all teams a user has access to."""
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        result = warm_user_teams_cache_task(user_id=42)

        mock_get_teams.assert_called_once_with(42)
        assert mock_warm.call_count == 2
        mock_warm.assert_any_call("phs_team1_123")
        mock_warm.assert_any_call("phs_team2_456")

        assert result["status"] == "success"
        assert result["user_id"] == 42
        assert result["teams_updated"] == 2

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_user_teams_cache_task_no_teams(self, mock_get_teams: MagicMock, mock_warm: MagicMock) -> None:
        """Test cache warming when user has no teams."""
        mock_get_teams.return_value = []

        result = warm_user_teams_cache_task(user_id=42)

        mock_get_teams.assert_called_once_with(42)
        mock_warm.assert_not_called()

        assert result["status"] == "success"
        assert result["user_id"] == 42
        assert result["teams_updated"] == 0

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_user_teams_cache_task_partial_failure(self, mock_get_teams: MagicMock, mock_warm: MagicMock) -> None:
        """Test cache warming handles individual team failures gracefully."""
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456", "phs_team3_789"]

        def warm_side_effect(project_api_key: str) -> bool:
            if project_api_key == "phs_team2_456":
                raise Exception("Cache warming failed for team 2")
            return True

        mock_warm.side_effect = warm_side_effect

        result = warm_user_teams_cache_task(user_id=42)

        # All teams were attempted
        assert mock_warm.call_count == 3

        # Partial success (2 of 3 succeeded)
        assert result["status"] == "success"
        assert result["user_id"] == 42
        assert result["teams_updated"] == 2

    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_user_teams_cache_task_systemic_failure(self, mock_get_teams: MagicMock) -> None:
        """Test cache warming returns failure on systemic errors."""
        mock_get_teams.side_effect = Exception("Database connection failed")

        result = warm_user_teams_cache_task(user_id=42)

        assert result["status"] == "failure"
        assert result["user_id"] == 42
        assert "Database connection failed" in result["error"]


class TestWarmPersonalApiKeyTeamsCacheTask(TestCase):
    """Test the PersonalAPIKey teams cache warming task."""

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_personal_api_key_teams_cache_task_success(
        self, mock_get_teams: MagicMock, mock_warm: MagicMock
    ) -> None:
        """Test successful cache warming after PersonalAPIKey change."""
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        result = warm_personal_api_key_teams_cache_task(user_id=42)

        mock_get_teams.assert_called_once_with(42)
        assert mock_warm.call_count == 2
        assert result["status"] == "success"
        assert result["user_id"] == 42
        assert result["teams_updated"] == 2

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.tasks.team_access_cache_tasks.get_teams_for_user_personal_api_keys")
    def test_warm_personal_api_key_teams_cache_task_no_teams(
        self, mock_get_teams: MagicMock, mock_warm: MagicMock
    ) -> None:
        """Test cache warming when user has no teams."""
        mock_get_teams.return_value = []

        result = warm_personal_api_key_teams_cache_task(user_id=42)

        mock_get_teams.assert_called_once_with(42)
        mock_warm.assert_not_called()
        assert result["status"] == "success"
        assert result["teams_updated"] == 0


class TestWarmPersonalApiKeyDeletedCacheTask(TestCase):
    """Test the PersonalAPIKey deletion cache warming task."""

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.models.team.team.Team")
    def test_warm_personal_api_key_deleted_cache_task_scoped_key(
        self, mock_team: MagicMock, mock_warm: MagicMock
    ) -> None:
        """Test cache warming for scoped key deletion."""
        mock_team.objects.filter.return_value.values_list.return_value = ["phs_team1_123", "phs_team2_456"]

        result = warm_personal_api_key_deleted_cache_task(user_id=42, scoped_team_ids=[1, 2])

        mock_team.objects.filter.assert_called_once_with(id__in=[1, 2])
        assert mock_warm.call_count == 2
        assert result["status"] == "success"
        assert result["teams_updated"] == 2

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.models.team.team.Team")
    @patch("posthog.models.organization.OrganizationMembership")
    def test_warm_personal_api_key_deleted_cache_task_unscoped_key(
        self, mock_membership: MagicMock, mock_team: MagicMock, mock_warm: MagicMock
    ) -> None:
        """Test cache warming for unscoped key deletion."""
        mock_membership.objects.filter.return_value.values_list.return_value = ["org-uuid-1"]
        mock_team.objects.filter.return_value.values_list.return_value = ["phs_team1_123"]

        result = warm_personal_api_key_deleted_cache_task(user_id=42, scoped_team_ids=None)

        mock_membership.objects.filter.assert_called_once_with(user_id=42)
        mock_team.objects.filter.assert_called_once()
        assert mock_warm.call_count == 1
        assert result["status"] == "success"
        assert result["teams_updated"] == 1


class TestWarmOrganizationTeamsCacheTask(TestCase):
    """Test the organization teams cache warming task."""

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.models.team.team.Team")
    def test_warm_organization_teams_cache_task_success(self, mock_team: MagicMock, mock_warm: MagicMock) -> None:
        """Test successful cache warming for organization teams."""
        mock_team.objects.filter.return_value.values_list.return_value = ["phs_team1_123", "phs_team2_456"]

        result = warm_organization_teams_cache_task(
            organization_id="org-uuid", user_id=42, action="added to organization"
        )

        mock_team.objects.filter.assert_called_once_with(organization_id="org-uuid")
        assert mock_warm.call_count == 2
        assert result["status"] == "success"
        assert result["organization_id"] == "org-uuid"
        assert result["user_id"] == 42
        assert result["teams_updated"] == 2

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.models.team.team.Team")
    def test_warm_organization_teams_cache_task_no_teams(self, mock_team: MagicMock, mock_warm: MagicMock) -> None:
        """Test cache warming when organization has no teams."""
        mock_team.objects.filter.return_value.values_list.return_value = []

        result = warm_organization_teams_cache_task(
            organization_id="org-uuid", user_id=42, action="removed from organization"
        )

        mock_warm.assert_not_called()
        assert result["status"] == "success"
        assert result["teams_updated"] == 0

    @patch("posthog.tasks.team_access_cache_tasks.warm_team_token_cache")
    @patch("posthog.models.team.team.Team")
    def test_warm_organization_teams_cache_task_partial_failure(
        self, mock_team: MagicMock, mock_warm: MagicMock
    ) -> None:
        """Test cache warming handles individual team failures gracefully."""
        mock_team.objects.filter.return_value.values_list.return_value = ["phs_team1_123", "phs_team2_456"]

        def warm_side_effect(project_api_key: str) -> bool:
            if project_api_key == "phs_team1_123":
                raise Exception("Cache warming failed")
            return True

        mock_warm.side_effect = warm_side_effect

        result = warm_organization_teams_cache_task(
            organization_id="org-uuid", user_id=42, action="added to organization"
        )

        assert mock_warm.call_count == 2
        assert result["status"] == "success"
        assert result["teams_updated"] == 1  # Only one succeeded


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
        with pytest.raises(Exception) as cm:
            warm_all_team_access_caches_task()

        mock_get_teams_paginated.assert_called_once()

        # Verify the exception is related to our test failure
        assert "Database connection failed" in str(cm.value)


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
