"""Tests for ingestion limits activities."""

from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.ingestion_limits.activities import (
    query_ingestion_limits_activity,
    report_ingestion_limits_activity,
)
from posthog.temporal.ingestion_limits.types import (
    HighVolumeDistinctId,
    IngestionLimitsReport,
    IngestionLimitsWorkflowInput,
    ReportDestination,
    ReportIngestionLimitsInput,
)

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
def mock_clickhouse_client():
    """Mock ClickHouse client."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@patch("posthog.temporal.ingestion_limits.activities.get_client")
async def test_query_ingestion_limits_activity(mock_get_client, mock_clickhouse_client):
    """Test query activity returns correct report."""
    mock_get_client.return_value = mock_clickhouse_client

    # Mock query results
    mock_rows = [
        {"team_id": 1, "distinct_id": "user1", "offending_event_count": 1500},
        {"team_id": 2, "distinct_id": "user2", "offending_event_count": 800},
        {"team_id": 1, "distinct_id": "user3", "offending_event_count": 500},
    ]

    async def mock_stream(*args, **kwargs):
        for row in mock_rows:
            yield row

    mock_clickhouse_client.stream_query_as_jsonl = mock_stream

    inputs = IngestionLimitsWorkflowInput(event_threshold=1000, time_window_minutes=60)

    result = await query_ingestion_limits_activity(inputs)

    assert isinstance(result, IngestionLimitsReport)
    assert len(result.high_volume_distinct_ids) == 1
    assert result.high_volume_distinct_ids[0].team_id == 1
    assert result.high_volume_distinct_ids[0].distinct_id == "user1"
    assert result.high_volume_distinct_ids[0].offending_event_count == 1500
    assert result.total_candidates == 3
    assert result.time_window_minutes == 60


@patch("posthog.temporal.ingestion_limits.activities.send_to_slack")
@patch("posthog.temporal.ingestion_limits.activities.send_to_kafka")
async def test_report_ingestion_limits_activity_slack(mock_send_kafka, mock_send_slack):
    """Test report activity sends to Slack when configured."""
    report = IngestionLimitsReport(
        high_volume_distinct_ids=[HighVolumeDistinctId(team_id=1, distinct_id="user1", offending_event_count=1500)],
        total_candidates=3,
        timestamp=datetime.now(UTC),
        time_window_minutes=60,
    )

    inputs = ReportIngestionLimitsInput(
        workflow_inputs=IngestionLimitsWorkflowInput(
            report_destination=ReportDestination.SLACK,
            slack_channel="#alerts",
            event_threshold=1000,
        ),
        report=report,
    )

    await report_ingestion_limits_activity(inputs)

    mock_send_slack.assert_called_once()
    mock_send_kafka.assert_not_called()


@patch("posthog.temporal.ingestion_limits.activities.send_to_slack")
@patch("posthog.temporal.ingestion_limits.activities.send_to_kafka")
async def test_report_ingestion_limits_activity_kafka(mock_send_kafka, mock_send_slack):
    """Test report activity sends to Kafka when configured."""
    report = IngestionLimitsReport(
        high_volume_distinct_ids=[HighVolumeDistinctId(team_id=1, distinct_id="user1", offending_event_count=1500)],
        total_candidates=3,
        timestamp=datetime.now(UTC),
        time_window_minutes=60,
    )

    inputs = ReportIngestionLimitsInput(
        workflow_inputs=IngestionLimitsWorkflowInput(
            report_destination=ReportDestination.KAFKA,
            kafka_topic="test_topic",
            event_threshold=1000,
        ),
        report=report,
    )

    await report_ingestion_limits_activity(inputs)

    mock_send_kafka.assert_called_once()
    mock_send_slack.assert_not_called()


@patch("posthog.temporal.ingestion_limits.activities.send_to_slack")
@patch("posthog.temporal.ingestion_limits.activities.send_to_kafka")
async def test_report_ingestion_limits_activity_both(mock_send_kafka, mock_send_slack):
    """Test report activity sends to both when configured."""
    report = IngestionLimitsReport(
        high_volume_distinct_ids=[HighVolumeDistinctId(team_id=1, distinct_id="user1", offending_event_count=1500)],
        total_candidates=3,
        timestamp=datetime.now(UTC),
        time_window_minutes=60,
    )

    inputs = ReportIngestionLimitsInput(
        workflow_inputs=IngestionLimitsWorkflowInput(
            report_destination=ReportDestination.BOTH,
            slack_channel="#alerts",
            kafka_topic="test_topic",
            event_threshold=1000,
        ),
        report=report,
    )

    await report_ingestion_limits_activity(inputs)

    mock_send_slack.assert_called_once()
    mock_send_kafka.assert_called_once()
