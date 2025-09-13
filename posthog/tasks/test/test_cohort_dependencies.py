from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.cohort import Cohort
from posthog.models.team import Team
from posthog.tasks.cohort_dependencies import (
    COHORT_CACHE_WARMING_MIN_COHORTS,
    _get_teams_with_cohorts_paginated,
    decrement_active_chains_gauge,
    warm_cohort_dependencies_cache_for_all_teams,
    warm_cohort_dependencies_cache_for_team,
)


class TestCohortCacheWarming(BaseTest):
    @parameterized.expand(
        [
            (49, False),  # Below threshold
            (50, True),  # At threshold
            (75, True),  # Above threshold
            (0, False),  # No cohorts
        ]
    )
    def test_get_teams_with_cohorts_paginated_filters_by_cohort_count(
        self, cohort_count: int, should_be_included: bool
    ) -> None:
        """Test that teams are filtered based on cohort count threshold"""
        team = Team.objects.create(organization=self.organization, name=f"Team with {cohort_count} cohorts")

        # Create the specified number of cohorts
        for i in range(cohort_count):
            Cohort.objects.create(
                team=team,
                name=f"Test Cohort {i}",
                deleted=False,
            )

        # Get teams from pagination
        teams_found = []
        for teams_page in _get_teams_with_cohorts_paginated(batch_size=100):
            teams_found.extend(teams_page)

        if should_be_included:
            self.assertIn(team.id, teams_found)
        else:
            self.assertNotIn(team.id, teams_found)

    def test_get_teams_with_cohorts_paginated_excludes_deleted_cohorts(self) -> None:
        """Test that deleted cohorts are not counted towards the threshold"""
        team = Team.objects.create(organization=self.organization, name="Team with deleted cohorts")

        # Create cohorts at threshold
        for i in range(COHORT_CACHE_WARMING_MIN_COHORTS):
            Cohort.objects.create(
                team=team,
                name=f"Test Cohort {i}",
                deleted=False,
            )

        # Create additional deleted cohorts
        for i in range(10):
            Cohort.objects.create(
                team=team,
                name=f"Deleted Cohort {i}",
                deleted=True,
            )

        teams_found = []
        for teams_page in _get_teams_with_cohorts_paginated(batch_size=100):
            teams_found.extend(teams_page)

        self.assertIn(team.id, teams_found, "Team should be included when non-deleted cohorts meet threshold")

    @parameterized.expand(
        [
            (100, 50),  # Teams fit in one page
            (100, 150),  # Teams require multiple pages
            (25, 100),  # Small page size, multiple pages needed
        ]
    )
    def test_get_teams_with_cohorts_paginated_handles_pagination(self, page_size: int, num_teams: int) -> None:
        """Test that pagination works correctly with different page sizes"""
        # Create teams with enough cohorts to meet threshold
        expected_team_ids = []
        for i in range(num_teams):
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            for j in range(COHORT_CACHE_WARMING_MIN_COHORTS):
                Cohort.objects.create(
                    team=team,
                    name=f"Team {i} Cohort {j}",
                    deleted=False,
                )
            expected_team_ids.append(team.id)

        # Collect all teams through pagination
        all_teams_found = []
        page_count = 0
        for teams_page in _get_teams_with_cohorts_paginated(batch_size=page_size):
            all_teams_found.extend(teams_page)
            page_count += 1
            # Ensure each page respects size limit
            self.assertLessEqual(len(teams_page), page_size)

        # Verify all expected teams were found
        self.assertEqual(set(all_teams_found), set(expected_team_ids))

        # Verify pagination occurred when expected
        expected_pages = (num_teams + page_size - 1) // page_size  # Ceiling division
        self.assertEqual(page_count, expected_pages)

    def test_get_teams_with_cohorts_paginated_returns_empty_when_no_teams_qualify(self) -> None:
        """Test that pagination returns empty when no teams meet the threshold"""
        # Create a team with too few cohorts
        team = Team.objects.create(organization=self.organization, name="Team with few cohorts")
        for i in range(COHORT_CACHE_WARMING_MIN_COHORTS - 1):
            Cohort.objects.create(
                team=team,
                name=f"Test Cohort {i}",
                deleted=False,
            )

        teams_found = []
        for teams_page in _get_teams_with_cohorts_paginated(batch_size=100):
            teams_found.extend(teams_page)

        self.assertEqual(teams_found, [])

    def test_get_teams_with_cohorts_paginated_orders_by_id(self) -> None:
        """Test that teams are returned in consistent ID order"""
        # Create teams in non-sequential order by creating them with gaps
        team_ids = []
        for i in [5, 1, 3, 2, 4]:
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            for j in range(COHORT_CACHE_WARMING_MIN_COHORTS):
                Cohort.objects.create(
                    team=team,
                    name=f"Team {i} Cohort {j}",
                    deleted=False,
                )
            team_ids.append(team.id)

        all_teams_found = []
        for teams_page in _get_teams_with_cohorts_paginated(batch_size=100):
            all_teams_found.extend(teams_page)

        # Verify teams are returned in ID order
        self.assertEqual(all_teams_found, sorted(all_teams_found))

    @patch("posthog.tasks.cohort_dependencies.chain")
    @patch("posthog.tasks.cohort_dependencies.warm_cohort_dependencies_cache_for_team.si")
    @patch("posthog.tasks.cohort_dependencies.decrement_active_chains_gauge.si")
    def test_warm_cohort_dependencies_cache_for_all_teams_creates_chains(
        self, mock_decrement_task: MagicMock, mock_warm_task: MagicMock, mock_chain: MagicMock
    ) -> None:
        """Test that the main task creates chains of tasks correctly"""
        # Create teams that meet threshold
        team_ids = []
        for i in range(3):
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            for j in range(COHORT_CACHE_WARMING_MIN_COHORTS):
                Cohort.objects.create(team=team, name=f"Team {i} Cohort {j}", deleted=False)
            team_ids.append(team.id)

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance
        mock_warm_task.return_value = MagicMock()
        mock_decrement_task.return_value = MagicMock()

        result = warm_cohort_dependencies_cache_for_all_teams()

        # Verify result structure
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["teams_found"], 3)
        self.assertEqual(result["teams_scheduled"], 3)
        self.assertEqual(result["failed_teams"], 0)

        # Verify chain was created and called
        mock_chain.assert_called_once()
        mock_chain_instance.apply_async.assert_called_once()

        # Verify warming tasks were created for all teams
        self.assertEqual(mock_warm_task.call_count, 3)
        scheduled_team_ids = {call[0][0] for call in mock_warm_task.call_args_list}
        self.assertEqual(scheduled_team_ids, set(team_ids))

        # Verify decrement task was added to chain
        mock_decrement_task.assert_called_once()

    @patch("posthog.tasks.cohort_dependencies.COHORT_CACHE_WARMING_BATCH_SIZE", 2)
    @patch("posthog.tasks.cohort_dependencies.chain")
    @patch("posthog.tasks.cohort_dependencies.warm_cohort_dependencies_cache_for_team.si")
    @patch("posthog.tasks.cohort_dependencies.decrement_active_chains_gauge.si")
    def test_warm_cohort_dependencies_cache_for_all_teams_respects_batch_size(
        self, mock_decrement_task: MagicMock, mock_warm_task: MagicMock, mock_chain: MagicMock
    ) -> None:
        """Test that teams are batched according to COHORT_CACHE_WARMING_BATCH_SIZE"""
        # Create 5 teams (will create 3 batches: 2, 2, 1 within a single page)
        for i in range(5):
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            for j in range(COHORT_CACHE_WARMING_MIN_COHORTS):
                Cohort.objects.create(team=team, name=f"Team {i} Cohort {j}", deleted=False)

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance

        result = warm_cohort_dependencies_cache_for_all_teams()

        # Should have created 3 separate chains (batches of 2, 2, 1 within the page)
        self.assertEqual(mock_chain.call_count, 3)
        self.assertEqual(mock_chain_instance.apply_async.call_count, 3)
        self.assertEqual(result["teams_scheduled"], 5)

    @patch("posthog.tasks.cohort_dependencies.COHORT_CACHE_WARMING_ACTIVE_CHAINS")
    @patch("posthog.tasks.cohort_dependencies.chain")
    @patch("posthog.tasks.cohort_dependencies.warm_cohort_dependencies_cache_for_team.si")
    def test_warm_cohort_dependencies_cache_for_all_teams_increments_gauge(
        self, mock_warm_task: MagicMock, mock_chain: MagicMock, mock_gauge: MagicMock
    ) -> None:
        """Test that the active chains gauge is incremented for each chain created"""
        # Create teams that will result in 2 chains (batch size is 50 by default)
        for i in range(75):  # Will create 2 batches: 50 and 25
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            for j in range(COHORT_CACHE_WARMING_MIN_COHORTS):
                Cohort.objects.create(team=team, name=f"Team {i} Cohort {j}", deleted=False)

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance

        warm_cohort_dependencies_cache_for_all_teams()

        # Should have incremented gauge twice (once per chain)
        self.assertEqual(mock_gauge.inc.call_count, 2)

    @patch("posthog.tasks.cohort_dependencies.chain")
    @patch("posthog.tasks.cohort_dependencies.warm_cohort_dependencies_cache_for_team.si")
    def test_warm_cohort_dependencies_cache_for_all_teams_handles_chain_failure(
        self, mock_warm_task: MagicMock, mock_chain: MagicMock
    ) -> None:
        """Test that chain creation failures are handled gracefully"""
        # Create a team
        team = Team.objects.create(organization=self.organization, name="Test Team")
        for i in range(COHORT_CACHE_WARMING_MIN_COHORTS):
            Cohort.objects.create(team=team, name=f"Cohort {i}", deleted=False)

        # Make chain creation fail
        mock_chain.side_effect = Exception("Chain creation failed")

        result = warm_cohort_dependencies_cache_for_all_teams()

        # Should handle failure gracefully
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["teams_found"], 1)
        self.assertEqual(result["teams_scheduled"], 0)
        self.assertEqual(result["failed_teams"], 1)

    @patch("posthog.tasks.cohort_dependencies.warm_team_cohort_dependency_cache")
    def test_warm_cohort_dependencies_cache_for_team_success(self, mock_warm_cache: MagicMock) -> None:
        """Test that individual team warming task calls the cache warming function"""
        mock_warm_cache.return_value = None

        result = warm_cohort_dependencies_cache_for_team(self.team.id)

        mock_warm_cache.assert_called_once_with(self.team.id)
        self.assertEqual(result, {"status": "success", "team_id": self.team.id})

    @patch("posthog.tasks.cohort_dependencies.warm_team_cohort_dependency_cache")
    @patch("posthog.tasks.cohort_dependencies.logger")
    def test_warm_cohort_dependencies_cache_for_team_handles_failure(
        self, mock_logger: MagicMock, mock_warm_cache: MagicMock
    ) -> None:
        """Test that individual team warming task handles failures gracefully"""
        mock_warm_cache.side_effect = Exception("Cache warming failed")

        result = warm_cohort_dependencies_cache_for_team(self.team.id)

        mock_warm_cache.assert_called_once_with(self.team.id)
        self.assertEqual(result, {"status": "failure", "team_id": self.team.id})
        mock_logger.warning.assert_called_once()

    @patch("posthog.tasks.cohort_dependencies.COHORT_CACHE_WARMING_ACTIVE_CHAINS")
    def test_decrement_active_chains_gauge(self, mock_gauge: MagicMock) -> None:
        """Test that the gauge decrement function works correctly"""
        result = decrement_active_chains_gauge()

        mock_gauge.dec.assert_called_once()
        self.assertEqual(result, {"status": "success"})

    def test_warm_cohort_dependencies_cache_for_all_teams_handles_empty_results(self) -> None:
        """Test behavior when no teams meet the criteria"""
        # Don't create any teams that meet the threshold
        team = Team.objects.create(organization=self.organization, name="Team with few cohorts")
        for i in range(COHORT_CACHE_WARMING_MIN_COHORTS - 1):
            Cohort.objects.create(team=team, name=f"Cohort {i}", deleted=False)

        result = warm_cohort_dependencies_cache_for_all_teams()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["teams_found"], 0)
        self.assertEqual(result["teams_scheduled"], 0)
        self.assertEqual(result["failed_teams"], 0)

    @freeze_time("2021-01-01T12:00:00Z")
    @patch("posthog.tasks.cohort_dependencies.chain")
    def test_warm_cohort_dependencies_cache_for_all_teams_sets_expiration(self, mock_chain: MagicMock) -> None:
        """Test that chains are created with proper expiration time"""
        # Create a team that meets threshold
        team = Team.objects.create(organization=self.organization, name="Test Team")
        for i in range(COHORT_CACHE_WARMING_MIN_COHORTS):
            Cohort.objects.create(team=team, name=f"Cohort {i}", deleted=False)

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance

        warm_cohort_dependencies_cache_for_all_teams()

        # Verify apply_async was called with expires parameter
        mock_chain_instance.apply_async.assert_called_once()
        call_kwargs = mock_chain_instance.apply_async.call_args[1]
        self.assertIn("expires", call_kwargs)

        # Expiration should be 30 minutes from now
        expected_expiration = timezone.now() + timedelta(minutes=30)
        self.assertEqual(call_kwargs["expires"], expected_expiration)

    @patch("posthog.tasks.cohort_dependencies.logger")
    @patch("posthog.tasks.cohort_dependencies._get_teams_with_cohorts_paginated")
    def test_warm_cohort_dependencies_cache_for_all_teams_logs_correctly(
        self, mock_paginated: MagicMock, mock_logger: MagicMock
    ) -> None:
        """Test that the main task logs information correctly"""
        # Mock pagination to return teams across multiple pages
        mock_paginated.return_value = iter([[1, 2], [3]])

        with patch("posthog.tasks.cohort_dependencies.chain") as mock_chain:
            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            warm_cohort_dependencies_cache_for_all_teams()

        # Verify info logs (start and completion)
        self.assertEqual(len(mock_logger.info.call_args_list), 2)

        # Check specific log messages
        start_call = mock_logger.info.call_args_list[0]
        end_call = mock_logger.info.call_args_list[1]

        self.assertIn("Warming cohort dependencies cache", str(start_call))
        self.assertIn("Cohort cache warming completed", str(end_call))

        # Verify debug logs for page processing
        debug_calls = [call for call in mock_logger.debug.call_args_list if "Processing page of teams" in str(call)]
        self.assertEqual(len(debug_calls), 2)  # One for each page

    @patch("posthog.tasks.cohort_dependencies.logger")
    @patch("posthog.tasks.cohort_dependencies._get_teams_with_cohorts_paginated")
    def test_warm_cohort_dependencies_cache_for_all_teams_handles_pagination_exception(
        self, mock_paginated: MagicMock, mock_logger: MagicMock
    ) -> None:
        """Test that the task handles exceptions during pagination gracefully"""
        mock_paginated.side_effect = Exception("Database connection failed")

        with patch.object(warm_cohort_dependencies_cache_for_all_teams, "retry") as mock_retry:
            mock_retry.side_effect = Exception("Retry failed")  # Simulate retry exhaustion

            with self.assertRaises(Exception):
                warm_cohort_dependencies_cache_for_all_teams()

        mock_logger.exception.assert_called()
        mock_retry.assert_called_once()

    def test_get_teams_with_cohorts_paginated_uses_correct_page_size(self) -> None:
        """Test that pagination uses the configured page size"""
        # Create 3 teams that meet threshold
        expected_teams = []
        for i in range(3):
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            for j in range(COHORT_CACHE_WARMING_MIN_COHORTS):
                Cohort.objects.create(team=team, name=f"Team {i} Cohort {j}", deleted=False)
            expected_teams.append(team.id)

        # Test by directly passing batch_size parameter
        pages = list(_get_teams_with_cohorts_paginated(batch_size=2))

        # Should have 2 pages: [team1, team2], [team3]
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(pages[0]), 2)
        self.assertEqual(len(pages[1]), 1)

        # Verify all teams are included
        all_teams = []
        for page in pages:
            all_teams.extend(page)
        self.assertEqual(set(all_teams), set(expected_teams))

    @parameterized.expand(
        [
            (10, 5, 2),  # 10 teams, batch size 5, expect 2 chains
            (25, 10, 3),  # 25 teams, batch size 10, expect 3 chains
            (1, 50, 1),  # 1 team, large batch size, expect 1 chain
            (100, 25, 4),  # 100 teams, batch size 25, expect 4 chains
        ]
    )
    @patch("posthog.tasks.cohort_dependencies.chain")
    @patch("posthog.tasks.cohort_dependencies.warm_cohort_dependencies_cache_for_team.si")
    def test_batching_creates_expected_number_of_chains(
        self, num_teams: int, batch_size: int, expected_chains: int, mock_warm_task: MagicMock, mock_chain: MagicMock
    ) -> None:
        """Test that different team/batch size combinations create the expected number of chains"""
        # Create teams
        for i in range(num_teams):
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            for j in range(COHORT_CACHE_WARMING_MIN_COHORTS):
                Cohort.objects.create(team=team, name=f"Team {i} Cohort {j}", deleted=False)

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance

        with patch("posthog.tasks.cohort_dependencies.COHORT_CACHE_WARMING_BATCH_SIZE", batch_size):
            result = warm_cohort_dependencies_cache_for_all_teams()

        self.assertEqual(mock_chain.call_count, expected_chains)
        self.assertEqual(result["teams_scheduled"], num_teams)
        self.assertEqual(result["failed_teams"], 0)
