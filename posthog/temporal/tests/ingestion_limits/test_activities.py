"""Tests for ingestion limits activities."""

from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.ingestion_limits.activities import (
    query_ingestion_limits_activity,
    report_ingestion_limits_activity,
)
from posthog.temporal.ingestion_limits.types import (
    Classification,
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
async def test_query_ingestion_limits_activity(mock_get_client, mock_clickhouse_client, activity_environment):
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

    inputs = IngestionLimitsWorkflowInput(
        known_distinct_id_threshold=1000, ambiguous_distinct_id_threshold=1000, time_window_minutes=60
    )

    result = await activity_environment.run(query_ingestion_limits_activity, inputs)

    assert isinstance(result, IngestionLimitsReport)
    assert len(result.high_volume_distinct_ids) == 1
    assert result.high_volume_distinct_ids[0].team_id == 1
    assert result.high_volume_distinct_ids[0].distinct_id == "user1"
    assert result.high_volume_distinct_ids[0].offending_event_count == 1500
    assert result.high_volume_distinct_ids[0].classification == Classification.AMBIGUOUS
    assert result.total_candidates == 3
    assert result.time_window_minutes == 60


@patch("posthog.temporal.ingestion_limits.activities.get_client")
async def test_query_ingestion_limits_activity_uuid_uses_known_threshold(
    mock_get_client, mock_clickhouse_client, activity_environment
):
    """Test that UUID distinct_ids use known_distinct_id_threshold."""
    mock_get_client.return_value = mock_clickhouse_client

    uuid_distinct_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_rows = [
        {"team_id": 1, "distinct_id": uuid_distinct_id, "offending_event_count": 1500},
        {"team_id": 2, "distinct_id": uuid_distinct_id, "offending_event_count": 800},
    ]

    async def mock_stream(*args, **kwargs):
        for row in mock_rows:
            yield row

    mock_clickhouse_client.stream_query_as_jsonl = mock_stream

    # Set different thresholds - UUID should use known threshold (1000)
    inputs = IngestionLimitsWorkflowInput(
        known_distinct_id_threshold=1000, ambiguous_distinct_id_threshold=5000, time_window_minutes=60
    )

    result = await activity_environment.run(query_ingestion_limits_activity, inputs)

    assert isinstance(result, IngestionLimitsReport)
    assert len(result.high_volume_distinct_ids) == 1
    assert result.high_volume_distinct_ids[0].distinct_id == uuid_distinct_id
    assert result.high_volume_distinct_ids[0].classification == Classification.UUID
    assert result.high_volume_distinct_ids[0].offending_event_count == 1500
    # Should be included because 1500 >= 1000 (known threshold), not 5000 (ambiguous threshold)


@patch("posthog.temporal.ingestion_limits.activities.get_client")
async def test_query_ingestion_limits_activity_email_uses_known_threshold(
    mock_get_client, mock_clickhouse_client, activity_environment
):
    """Test that EMAIL distinct_ids use known_distinct_id_threshold."""
    mock_get_client.return_value = mock_clickhouse_client

    email_distinct_id = "test@example.com"
    mock_rows = [
        {"team_id": 1, "distinct_id": email_distinct_id, "offending_event_count": 1500},
        {"team_id": 2, "distinct_id": email_distinct_id, "offending_event_count": 800},
    ]

    async def mock_stream(*args, **kwargs):
        for row in mock_rows:
            yield row

    mock_clickhouse_client.stream_query_as_jsonl = mock_stream

    # Set different thresholds - EMAIL should use known threshold (1000)
    inputs = IngestionLimitsWorkflowInput(
        known_distinct_id_threshold=1000, ambiguous_distinct_id_threshold=5000, time_window_minutes=60
    )

    result = await activity_environment.run(query_ingestion_limits_activity, inputs)

    assert isinstance(result, IngestionLimitsReport)
    assert len(result.high_volume_distinct_ids) == 1
    assert result.high_volume_distinct_ids[0].distinct_id == email_distinct_id
    assert result.high_volume_distinct_ids[0].classification == Classification.EMAIL
    assert result.high_volume_distinct_ids[0].offending_event_count == 1500
    # Should be included because 1500 >= 1000 (known threshold), not 5000 (ambiguous threshold)


@patch("posthog.temporal.ingestion_limits.activities.get_client")
async def test_query_ingestion_limits_activity_ambiguous_uses_ambiguous_threshold(
    mock_get_client, mock_clickhouse_client, activity_environment
):
    """Test that AMBIGUOUS distinct_ids use ambiguous_distinct_id_threshold."""
    mock_get_client.return_value = mock_clickhouse_client

    ambiguous_distinct_id = "user123"
    mock_rows = [
        {"team_id": 1, "distinct_id": ambiguous_distinct_id, "offending_event_count": 1500},
        {"team_id": 2, "distinct_id": ambiguous_distinct_id, "offending_event_count": 800},
    ]

    async def mock_stream(*args, **kwargs):
        for row in mock_rows:
            yield row

    mock_clickhouse_client.stream_query_as_jsonl = mock_stream

    # Set different thresholds - AMBIGUOUS should use ambiguous threshold (5000)
    inputs = IngestionLimitsWorkflowInput(
        known_distinct_id_threshold=1000, ambiguous_distinct_id_threshold=5000, time_window_minutes=60
    )

    result = await activity_environment.run(query_ingestion_limits_activity, inputs)

    assert isinstance(result, IngestionLimitsReport)
    assert len(result.high_volume_distinct_ids) == 0
    # Should be excluded because 1500 < 5000 (ambiguous threshold), even though 1500 >= 1000 (known threshold)


@patch("posthog.temporal.ingestion_limits.activities.get_client")
async def test_query_ingestion_limits_activity_mixed_classifications(
    mock_get_client, mock_clickhouse_client, activity_environment
):
    """Test query activity with mixed distinct_id classifications."""
    mock_get_client.return_value = mock_clickhouse_client

    uuid_id = "550e8400-e29b-41d4-a716-446655440000"
    email_id = "test@example.com"
    ambiguous_id = "user123"
    mock_rows = [
        {"team_id": 1, "distinct_id": uuid_id, "offending_event_count": 1500},  # Should be included (1500 >= 1000)
        {"team_id": 2, "distinct_id": email_id, "offending_event_count": 1200},  # Should be included (1200 >= 1000)
        {"team_id": 3, "distinct_id": ambiguous_id, "offending_event_count": 1500},  # Should be excluded (1500 < 5000)
        {"team_id": 4, "distinct_id": ambiguous_id, "offending_event_count": 6000},  # Should be included (6000 >= 5000)
    ]

    async def mock_stream(*args, **kwargs):
        for row in mock_rows:
            yield row

    mock_clickhouse_client.stream_query_as_jsonl = mock_stream

    inputs = IngestionLimitsWorkflowInput(
        known_distinct_id_threshold=1000, ambiguous_distinct_id_threshold=5000, time_window_minutes=60
    )

    result = await activity_environment.run(query_ingestion_limits_activity, inputs)

    assert isinstance(result, IngestionLimitsReport)
    assert len(result.high_volume_distinct_ids) == 3
    assert result.total_candidates == 4

    # Verify UUID classification
    uuid_item = next((item for item in result.high_volume_distinct_ids if item.distinct_id == uuid_id), None)
    assert uuid_item is not None
    assert uuid_item.classification == Classification.UUID

    # Verify EMAIL classification
    email_item = next((item for item in result.high_volume_distinct_ids if item.distinct_id == email_id), None)
    assert email_item is not None
    assert email_item.classification == Classification.EMAIL

    # Verify AMBIGUOUS classification (only the one above threshold)
    ambiguous_items = [item for item in result.high_volume_distinct_ids if item.distinct_id == ambiguous_id]
    assert len(ambiguous_items) == 1
    assert ambiguous_items[0].classification == Classification.AMBIGUOUS
    assert ambiguous_items[0].offending_event_count == 6000


@patch("posthog.temporal.ingestion_limits.activities.send_to_slack")
@patch("posthog.temporal.ingestion_limits.activities.send_to_kafka")
async def test_report_ingestion_limits_activity_slack(mock_send_kafka, mock_send_slack, activity_environment):
    """Test report activity sends to Slack when configured."""
    report = IngestionLimitsReport(
        high_volume_distinct_ids=[
            HighVolumeDistinctId(
                team_id=1, distinct_id="user1", offending_event_count=1500, classification=Classification.AMBIGUOUS
            )
        ],
        total_candidates=3,
        timestamp=datetime.now(UTC),
        known_distinct_id_threshold=1000,
        ambiguous_distinct_id_threshold=1000,
        time_window_minutes=60,
    )

    inputs = ReportIngestionLimitsInput(
        workflow_inputs=IngestionLimitsWorkflowInput(
            report_destination=ReportDestination.SLACK,
            slack_channel="#alerts",
            known_distinct_id_threshold=1000,
            ambiguous_distinct_id_threshold=1000,
        ),
        report=report,
    )

    await activity_environment.run(report_ingestion_limits_activity, inputs)

    mock_send_slack.assert_called_once()
    mock_send_kafka.assert_not_called()


@patch("posthog.temporal.ingestion_limits.activities.send_to_slack")
@patch("posthog.temporal.ingestion_limits.activities.send_to_kafka")
async def test_report_ingestion_limits_activity_kafka(mock_send_kafka, mock_send_slack, activity_environment):
    """Test report activity sends to Kafka when configured."""
    report = IngestionLimitsReport(
        high_volume_distinct_ids=[
            HighVolumeDistinctId(
                team_id=1, distinct_id="user1", offending_event_count=1500, classification=Classification.AMBIGUOUS
            )
        ],
        total_candidates=3,
        timestamp=datetime.now(UTC),
        known_distinct_id_threshold=1000,
        ambiguous_distinct_id_threshold=1000,
        time_window_minutes=60,
    )

    inputs = ReportIngestionLimitsInput(
        workflow_inputs=IngestionLimitsWorkflowInput(
            report_destination=ReportDestination.KAFKA,
            kafka_topic="test_topic",
            known_distinct_id_threshold=1000,
            ambiguous_distinct_id_threshold=1000,
        ),
        report=report,
    )

    await activity_environment.run(report_ingestion_limits_activity, inputs)

    mock_send_kafka.assert_called_once()
    mock_send_slack.assert_not_called()


@patch("posthog.temporal.ingestion_limits.activities.send_to_slack")
@patch("posthog.temporal.ingestion_limits.activities.send_to_kafka")
async def test_report_ingestion_limits_activity_both(mock_send_kafka, mock_send_slack, activity_environment):
    """Test report activity sends to both when configured."""
    report = IngestionLimitsReport(
        high_volume_distinct_ids=[
            HighVolumeDistinctId(
                team_id=1, distinct_id="user1", offending_event_count=1500, classification=Classification.AMBIGUOUS
            )
        ],
        total_candidates=3,
        timestamp=datetime.now(UTC),
        known_distinct_id_threshold=1000,
        ambiguous_distinct_id_threshold=1000,
        time_window_minutes=60,
    )

    inputs = ReportIngestionLimitsInput(
        workflow_inputs=IngestionLimitsWorkflowInput(
            report_destination=ReportDestination.BOTH,
            slack_channel="#alerts",
            kafka_topic="test_topic",
            known_distinct_id_threshold=1000,
            ambiguous_distinct_id_threshold=1000,
        ),
        report=report,
    )

    await activity_environment.run(report_ingestion_limits_activity, inputs)

    mock_send_slack.assert_called_once()
    mock_send_kafka.assert_called_once()
