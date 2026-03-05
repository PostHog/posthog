from datetime import UTC, datetime

from unittest import mock

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.dags.distinct_id_usage import (
    BurstEvent,
    DistinctIdUsageMonitoringConfig,
    HighCardinalityTeam,
    HighUsageDistinctId,
    MonitoringResults,
    generate_csv_report,
    get_last_successful_run_time,
    query_distinct_id_usage,
    send_alerts,
    truncate_distinct_id,
)
from posthog.models.distinct_id_usage.sql import DATA_TABLE_NAME


class TestTruncateDistinctId:
    def test_short_string_unchanged(self):
        assert truncate_distinct_id("short", max_length=30) == "short"

    def test_exact_length_unchanged(self):
        assert truncate_distinct_id("a" * 30, max_length=30) == "a" * 30

    def test_long_string_truncated(self):
        result = truncate_distinct_id("a" * 50, max_length=30)
        assert len(result) == 30
        assert result.endswith("...")

    def test_custom_max_length(self):
        result = truncate_distinct_id("hello world", max_length=8)
        assert result == "hello..."
        assert len(result) == 8


class TestGetLastSuccessfulRunTime:
    def test_returns_none_when_no_previous_runs(self):
        mock_context = mock.MagicMock(spec=dagster.OpExecutionContext)
        mock_context.instance.get_run_records.return_value = []

        result = get_last_successful_run_time(mock_context)

        assert result is None

    def test_returns_end_time_of_last_successful_run(self):
        mock_context = mock.MagicMock(spec=dagster.OpExecutionContext)
        expected_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        mock_record = mock.MagicMock()
        mock_record.end_time = expected_time.timestamp()
        mock_context.instance.get_run_records.return_value = [mock_record]

        result = get_last_successful_run_time(mock_context)

        assert result == expected_time

    def test_returns_none_when_end_time_is_none(self):
        mock_context = mock.MagicMock(spec=dagster.OpExecutionContext)
        mock_record = mock.MagicMock()
        mock_record.end_time = None
        mock_context.instance.get_run_records.return_value = [mock_record]

        result = get_last_successful_run_time(mock_context)

        assert result is None


class TestGenerateCsvReport:
    def test_empty_results(self):
        results = MonitoringResults(
            high_usage=[],
            high_cardinality=[],
            bursts=[],
            lookback_start=datetime(2025, 1, 15, tzinfo=UTC),
        )

        csv_output = generate_csv_report(results)

        assert "=== HIGH USAGE DISTINCT IDS ===" in csv_output
        assert "=== HIGH CARDINALITY TEAMS ===" in csv_output
        assert "=== BURST EVENTS ===" in csv_output

    def test_includes_high_usage_data(self):
        results = MonitoringResults(
            high_usage=[
                HighUsageDistinctId(
                    team_id=1,
                    distinct_id="test_user",
                    event_count=1000,
                    total_team_events=2000,
                    percentage=50.0,
                )
            ],
            high_cardinality=[],
            bursts=[],
            lookback_start=datetime(2025, 1, 15, tzinfo=UTC),
        )

        csv_output = generate_csv_report(results)

        assert "1,test_user,1000,2000,50.0" in csv_output

    def test_includes_high_cardinality_data(self):
        results = MonitoringResults(
            high_usage=[],
            high_cardinality=[HighCardinalityTeam(team_id=42, distinct_id_count=1500000)],
            bursts=[],
            lookback_start=datetime(2025, 1, 15, tzinfo=UTC),
        )

        csv_output = generate_csv_report(results)

        assert "42,1500000" in csv_output

    def test_includes_burst_data(self):
        results = MonitoringResults(
            high_usage=[],
            high_cardinality=[],
            bursts=[
                BurstEvent(
                    team_id=5,
                    distinct_id="burst_user",
                    minute="2025-01-15 10:00:00",
                    event_count=50000,
                )
            ],
            lookback_start=datetime(2025, 1, 15, tzinfo=UTC),
        )

        csv_output = generate_csv_report(results)

        assert "5,burst_user,2025-01-15 10:00:00,50000" in csv_output


class TestMonitoringResultsDataclasses:
    def test_high_usage_distinct_id(self):
        item = HighUsageDistinctId(
            team_id=1,
            distinct_id="user123",
            event_count=500,
            total_team_events=1000,
            percentage=50.0,
        )
        assert item.team_id == 1
        assert item.distinct_id == "user123"
        assert item.event_count == 500
        assert item.total_team_events == 1000
        assert item.percentage == 50.0

    def test_high_cardinality_team(self):
        item = HighCardinalityTeam(team_id=42, distinct_id_count=2000000)
        assert item.team_id == 42
        assert item.distinct_id_count == 2000000

    def test_burst_event(self):
        item = BurstEvent(
            team_id=5,
            distinct_id="burst_user",
            minute="2025-01-15 10:00:00",
            event_count=15000,
        )
        assert item.team_id == 5
        assert item.distinct_id == "burst_user"
        assert item.minute == "2025-01-15 10:00:00"
        assert item.event_count == 15000


class TestSendAlerts:
    def test_skips_alert_when_all_results_empty(self):
        """Verify that no Slack message is sent when all results are empty."""
        empty_results = MonitoringResults(
            high_usage=[],
            high_cardinality=[],
            bursts=[],
            lookback_start=datetime(2025, 1, 15, tzinfo=UTC),
        )

        context = dagster.build_op_context()
        mock_slack = mock.MagicMock()

        # Call send_alerts with empty results
        send_alerts(context, empty_results, mock_slack)

        # Verify that get_client was never called (no Slack message sent)
        mock_slack.get_client.assert_not_called()


def test_query_distinct_id_usage(cluster: ClickhouseCluster) -> None:
    """Integration test for the query_distinct_id_usage op."""
    now = datetime.now(tz=UTC).replace(second=0, microsecond=0)

    # Insert test data directly into the sharded table
    cluster.any_host(
        Query(
            f"INSERT INTO {DATA_TABLE_NAME} (team_id, distinct_id, minute, event_count) VALUES",
            [
                # High usage: one distinct_id with 80% of team's events (120k events)
                (1, "high_usage_user", now, 120000),
                (1, "normal_user_1", now, 15000),
                (1, "normal_user_2", now, 15000),
                # High cardinality team: many unique distinct_ids
                *[(2, f"user_{i}", now, 1) for i in range(100)],
                # Burst event: high events in single minute (150k events)
                (3, "burst_user", now, 150000),
            ],
        )
    ).result()

    # Create config with thresholds that will match our test data
    config = DistinctIdUsageMonitoringConfig(
        high_usage_percentage_threshold=70,  # 80% > 70%
        high_usage_min_events_threshold=50000,  # 150k total events > 50k
        high_usage_distinct_id_min_events=100000,  # 120k events > 100k
        high_cardinality_threshold=50,  # 100 > 50
        burst_threshold=100000,  # 150k > 100k
        default_lookback_hours=2,
    )

    # Build proper dagster op context
    context = dagster.build_op_context()

    # Run the query
    results = query_distinct_id_usage(context, config, cluster)

    # Verify high usage detection
    assert len(results.high_usage) >= 1
    high_usage_user = next((h for h in results.high_usage if h.distinct_id == "high_usage_user"), None)
    assert high_usage_user is not None
    assert high_usage_user.team_id == 1
    assert high_usage_user.percentage >= 70

    # Verify high cardinality detection
    assert len(results.high_cardinality) >= 1
    high_card_team = next((h for h in results.high_cardinality if h.team_id == 2), None)
    assert high_card_team is not None
    assert high_card_team.distinct_id_count >= 50

    # Verify burst detection
    assert len(results.bursts) >= 1
    burst = next((b for b in results.bursts if b.distinct_id == "burst_user"), None)
    assert burst is not None
    assert burst.team_id == 3
    assert burst.event_count >= 100000
