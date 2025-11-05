"""Tests for ingestion limits workflows."""

from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner

from posthog.temporal.ingestion_limits.activities import (
    query_ingestion_limits_activity,
    report_ingestion_limits_activity,
)
from posthog.temporal.ingestion_limits.types import IngestionLimitsWorkflowInput, ReportDestination
from posthog.temporal.ingestion_limits.workflows import IngestionLimitsWorkflow

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
async def workflow_environment():
    """Create a workflow test environment."""
    async with WorkflowEnvironment() as env:
        yield env


@patch("posthog.temporal.ingestion_limits.activities.get_client")
async def test_ingestion_limits_workflow(mock_get_client, workflow_environment):
    """Test ingestion limits workflow executes activities in order."""
    # Mock ClickHouse client
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_get_client.return_value = mock_client

    # Mock query results
    mock_rows = [
        {"team_id": 1, "distinct_id": "user1", "offending_event_count": 1500},
    ]

    async def mock_stream(*args, **kwargs):
        for row in mock_rows:
            yield row

    mock_client.stream_query_as_jsonl = mock_stream

    # Mock reporting functions
    with (
        patch("posthog.temporal.ingestion_limits.activities.send_to_slack") as mock_slack,
        patch("posthog.temporal.ingestion_limits.activities.send_to_kafka") as mock_kafka,
    ):
        inputs = IngestionLimitsWorkflowInput(
            event_threshold=1000,
            time_window_hours=1,
            report_destination=ReportDestination.BOTH,
            slack_channel="#test-channel",
            kafka_topic="test_topic",
        )

        async with workflow_environment.worker(
            UnsandboxedWorkflowRunner(),
            workflows=[IngestionLimitsWorkflow],
            activities=[query_ingestion_limits_activity, report_ingestion_limits_activity],
        ):
            await workflow_environment.client.execute_workflow(
                IngestionLimitsWorkflow.run,
                inputs,
                id=f"test-workflow-{datetime.now(UTC).timestamp()}",
                task_queue="test-task-queue",
            )

        # Verify query activity was called
        assert mock_get_client.called
        # Verify reporting functions were called (both should be called when destination is BOTH)
        mock_slack.assert_called_once()
        mock_kafka.assert_called_once()
