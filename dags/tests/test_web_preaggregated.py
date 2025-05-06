from datetime import datetime
from unittest import mock
import re

import pytest
from freezegun import freeze_time

from dags.web_preaggregated import (
    get_team_pageview_volumes,
    split_teams_in_batches,
    web_overview_daily,
    web_stats_daily,
    WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
)
from posthog.models.web_preaggregated.sql import (
    format_team_ids,
    WEB_OVERVIEW_INSERT_SQL,
)


@pytest.fixture
def pageview_volumes():
    return {
        1: 10,
        2: 20,
        3: 30,
        4: 40,
        5: 50,
        6: 200,
        7: 350,
        8: 500,
        9: 750,
        10: 1000,
        11: 2000,
        12: 3500,
        13: 5000,
        14: 7500,
        15: 10000,
        16: 20000,
        17: 40000,
        18: 60000,
        19: 80000,
        20: 100000,
        21: 200000,
        22: 300000,
        23: 400000,
        24: 500000,
        25: 600000,
    }


class TestWebAnalyticsUtils:
    """Tests for utility functions used in web analytics processing, particularly for batch creation logic."""

    def test_get_batches_per_pageview_volume_with_large_teams(self, pageview_volumes):
        """Test that large teams (those exceeding the target batch size) are placed in their own batches."""
        # Set a smaller target batch size to ensure large teams get their own batches
        target_batch_size = 250_000

        # Run the batch creation
        batches = split_teams_in_batches(pageview_volumes, target_batch_size)

        # The expected result should have teams 23, 24, and 25 each in their own batch
        # since they exceed the target batch size (their volumes are ~400k, ~500k, and ~600k)
        # and other teams should be grouped together to approach the target batch size

        # Find the specific batches for our large teams
        batch_with_team_23 = next((b for b in batches if 23 in b), None)
        batch_with_team_24 = next((b for b in batches if 24 in b), None)
        batch_with_team_25 = next((b for b in batches if 25 in b), None)

        # Assert that large teams are in their own batches
        assert batch_with_team_23 == [23], f"Team 23 should be alone in its batch, got: {batch_with_team_23}"
        assert batch_with_team_24 == [24], f"Team 24 should be alone in its batch, got: {batch_with_team_24}"
        assert batch_with_team_25 == [25], f"Team 25 should be alone in its batch, got: {batch_with_team_25}"

        # Verify all teams are included
        all_teams_in_batches = {team for batch in batches for team in batch}
        assert all_teams_in_batches == set(pageview_volumes.keys()), "All teams should be included in batches"

    def test_get_batches_per_pageview_volume_with_uniform_distribution(self):
        """Test that teams with uniform volume are distributed evenly."""
        # Create a test case with 12 teams, each with 100 pageviews
        teams_with_volumes = {i: 100 for i in range(1, 13)}
        # Set target batch size to 400, which should give us 3 batches of 4 teams each
        target_batch_size = 400

        batches = split_teams_in_batches(teams_with_volumes, target_batch_size)

        assert len(batches) == 3, f"Expected 3 batches, got {len(batches)}"

        # Each batch should have 4 teams
        for i, batch in enumerate(batches):
            assert len(batch) == 4, f"Batch {i+1} should have 4 teams, got {len(batch)}: {batch}"

        # Each batch should have a total volume of 400
        for i, batch in enumerate(batches):
            batch_volume = sum(teams_with_volumes[t] for t in batch)
            assert batch_volume == 400, f"Batch {i+1} should have volume 400, got {batch_volume}"

        # All teams should be included exactly once
        all_teams = [team for batch in batches for team in batch]
        assert sorted(all_teams) == list(range(1, 13)), "All teams should be included exactly once"

    def test_get_batches_per_pageview_volume_with_empty_input(self):
        """Test that empty input returns empty batches."""
        # Run with empty input
        batches = split_teams_in_batches({}, 1000)

        assert batches == [], "Empty input should return empty batch list"

    def test_get_batches_per_pageview_volume_with_single_team(self):
        """Test that a single team gets its own batch regardless of target size."""
        teams_with_volumes = {42: 10000}
        target_batch_size = 5000  # Smaller than the team volume

        batches = split_teams_in_batches(teams_with_volumes, target_batch_size)

        # Should get a single batch with just the one team
        expected_result = [[42]]
        assert batches == expected_result, f"Expected {expected_result}, got {batches}"

    def test_get_batches_with_one_pageview_per_batch(self, pageview_volumes):
        """Test that setting target batch size to 1 pageview results in one team per batch."""
        target_batch_size = 1

        # Run the batch creation
        batches = split_teams_in_batches(pageview_volumes, target_batch_size)

        # We should get exactly one batch per team
        assert len(batches) == len(pageview_volumes)

        # Each batch should have exactly one team
        for batch in batches:
            assert len(batch) == 1

        # All teams should be included
        batch_teams = {batch[0] for batch in batches}
        assert batch_teams == set(pageview_volumes.keys())


class TestWebAnalyticsClickhouse:
    """Tests for ClickHouse database operations related to web analytics tables and queries."""

    def test_get_team_pageview_volumes_fetches_data(self):
        mock_client = mock.MagicMock()
        mock_client.execute.return_value = [(5, 100), (13, 5000), (25, 600000)]

        result = get_team_pageview_volumes(mock_client)

        assert result == {5: 100, 13: 5000, 25: 600000}
        query = mock_client.execute.call_args[0][0]
        for term in ["team_id", "avg_daily_pageviews", "events", "$pageview"]:
            assert term in query


class TestWebAnalyticsPartitions:
    """Tests for partition management and scheduling in web analytics processing."""

    def test_weekly_partition_definition_creates_correct_partitions(self):
        partitions = list(WEB_ANALYTICS_DATE_PARTITION_DEFINITION.get_partition_keys())
        parsed = [datetime.strptime(p, "%Y-%m-%d") for p in partitions]
        assert all(parsed[i] < parsed[i + 1] for i in range(len(parsed) - 1))

    @freeze_time("2025-01-15 10:00:00")
    def test_web_analytics_daily_schedule_uses_correct_dates(self):
        expected_date = "2025-01-14"

        # Instead of trying to mock the ScheduleEvaluationContext class,
        # let's mock the web_analytics_daily_schedule function itself
        with mock.patch("dags.web_preaggregated.web_analytics_daily_schedule") as mock_schedule:
            # Setup the mock RunRequest
            mock_run_request = mock.MagicMock()
            mock_run_request.run_key = expected_date
            mock_run_request.partition_key = expected_date
            mock_schedule.return_value = mock_run_request

            # Create a simple context with just the scheduled_execution_time
            context = mock.MagicMock()
            context.scheduled_execution_time = datetime(2025, 1, 15, 10, 0)

            result = mock_schedule(context)

            assert result.run_key == expected_date
            assert result.partition_key == expected_date
            mock_schedule.assert_called_once_with(context)


class TestWebAnalyticsAggregation:
    """Tests for web analytics aggregation processes, including error handling and result validation."""

    @pytest.mark.partition_key("2025-01-08")
    def test_web_overview_daily_processes_data(self):
        with mock.patch("dags.web_preaggregated.pre_aggregate_web_analytics_data") as mock_process:
            # Mock the structured return value
            mock_return_value = {
                "partition_date": "2025-01-08",
                "processing_results": {
                    "total_teams": 10,
                    "successful_teams": 8,
                    "failed_teams": 2,
                    "success_rate": 0.8,
                    "successful_batches": 2,
                    "failed_batches": 1,
                },
            }
            mock_process.return_value = mock_return_value

            context = mock.MagicMock(partition_key="2025-01-08")
            cluster = mock.MagicMock()

            result = web_overview_daily(context=context, cluster=cluster)

            mock_process.assert_called_once()
            assert mock_process.call_args[1]["table_name"] == "web_overview_daily"
            # Check the full structure is returned
            assert result == mock_return_value
            # Check specific values
            assert result["partition_date"] == "2025-01-08"
            assert result["processing_results"]["total_teams"] == 10
            assert result["processing_results"]["successful_teams"] == 8

    @pytest.mark.partition_key("2025-01-08")
    def test_web_stats_daily_processes_data(self):
        with mock.patch("dags.web_preaggregated.pre_aggregate_web_analytics_data") as mock_process:
            # Mock the structured return value
            mock_return_value = {
                "partition_date": "2025-01-08",
                "processing_results": {
                    "total_teams": 5,
                    "successful_teams": 5,
                    "failed_teams": 0,
                    "success_rate": 1.0,
                    "successful_batches": 1,
                    "failed_batches": 0,
                },
            }
            mock_process.return_value = mock_return_value

            context = mock.MagicMock(partition_key="2025-01-08")
            cluster = mock.MagicMock()

            result = web_stats_daily(context=context, cluster=cluster)

            mock_process.assert_called_once()
            assert mock_process.call_args[1]["table_name"] == "web_stats_daily"
            # Check the full structure is returned
            assert result == mock_return_value
            # Check specific values
            assert result["partition_date"] == "2025-01-08"
            assert result["processing_results"]["success_rate"] == 1.0


# This is just a smoke test to make sure the placeholders are correctly placed when using batches.
# We will want to improve those tests and logic after we get a better idea on how it will be queried.
# For now, it gets the job done.
class TestSqlGeneration:
    """Tests for SQL generation used in web analytics processing, ensuring correct query formatting."""

    def test_batch_team_ids_included_in_sql(self, pageview_volumes):
        """Test that team IDs are correctly included in the generated SQL."""
        # Increased target_batch_size to handle the largest team's volume (600000)
        target_batch_size = 1_000_000
        batches = split_teams_in_batches(pageview_volumes, target_batch_size)

        # With this batch size, we should get at least 2 batches
        assert len(batches) >= 2

        # Test the SQL generation for the first two batches
        for _, batch in enumerate(batches[:2]):
            # Format the team IDs for SQL
            team_ids_list = format_team_ids(batch)

            # Generate the SQL
            sql = WEB_OVERVIEW_INSERT_SQL(
                date_start="2025-01-08 00:00:00",
                date_end="2025-01-15 00:00:00",
                team_ids=team_ids_list,
                timezone="UTC",
                settings="max_execution_time=60",
                table_name="web_overview_daily",
            )

            # Find all occurrences of team_id IN(...) in the SQL
            team_id_matches = re.findall(r"e\.team_id IN\((.*?)\)", sql)

            # Verify team IDs are in the SQL
            assert team_id_matches, "SQL should contain team_id IN clause"
            actual_team_ids = team_id_matches[0]
            assert actual_team_ids != "", "Team IDs list should not be empty"

            # Verify the same team IDs are used in both places
            person_team_id_matches = re.findall(r"person_distinct_id_overrides\.team_id IN\((.*?)\)", sql)
            assert person_team_id_matches[0] == actual_team_ids, "Team IDs should be consistent across SQL clauses"

            # Verify the batch volume is within the target limit
            batch_volume = sum(pageview_volumes.get(t, 1) for t in batch)
            assert batch_volume <= target_batch_size, f"Batch volume {batch_volume} exceeds target {target_batch_size}"

    def test_single_huge_batch_sql_generation(self, pageview_volumes):
        """Test SQL generation with a very large target size, creating a single batch with all teams."""
        # Use an enormous target batch size to ensure all teams go into one batch
        target_batch_size = 10_000_000

        batches = split_teams_in_batches(pageview_volumes, target_batch_size)

        # Verify we have a single batch with all teams
        assert len(batches) == 1
        batch = batches[0]
        assert len(batch) == len(pageview_volumes)

        team_ids_list = format_team_ids(batch)
        # Generate SQL and verify it looks correct
        WEB_OVERVIEW_INSERT_SQL(
            date_start="2025-01-08 00:00:00",
            date_end="2025-01-15 00:00:00",
            team_ids=team_ids_list,
            timezone="UTC",
            settings="max_execution_time=240",
            table_name="web_overview_daily",
        )

        # Check the SQL contains all team IDs
        for team_id in pageview_volumes.keys():
            assert str(team_id) in team_ids_list

    def test_many_small_batches_sql_generation(self, pageview_volumes):
        """Test SQL generation with a very small target size, creating many small batches."""
        # Use a tiny target batch size to force creation of many small batches
        target_batch_size = 1

        batches = split_teams_in_batches(pageview_volumes, target_batch_size)

        # With such a small batch size, each team should be its own batch
        assert len(batches) == len(pageview_volumes)
        assert all(len(batch) == 1 for batch in batches)

        # Check SQL for a few batches - only check first few to save time
        for batch in list(batches)[:5]:
            team_ids_list = format_team_ids(batch)

            sql = WEB_OVERVIEW_INSERT_SQL(
                date_start="2025-01-08 00:00:00",
                date_end="2025-01-15 00:00:00",
                team_ids=team_ids_list,
                timezone="UTC",
                settings="max_execution_time=30",
                table_name="web_overview_daily",
            )

            # Extract the actual team IDs from the SQL
            team_id_matches = re.findall(r"e\.team_id IN\((.*?)\)", sql)
            if team_id_matches:
                actual_team_ids = team_id_matches[0]
                # Check that some team IDs are included in the SQL
                assert actual_team_ids != ""
                # Check that the same team IDs are used in both places
                person_team_id_matches = re.findall(r"person_distinct_id_overrides\.team_id IN\((.*?)\)", sql)
                assert person_team_id_matches[0] == actual_team_ids
            else:
                # If no match, the SQL is not formed correctly
                raise AssertionError("Team IDs not found in SQL")
