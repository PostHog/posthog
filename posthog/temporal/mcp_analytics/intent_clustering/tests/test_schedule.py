"""Tests for the intent clustering coordinator schedule.

The schedule is gated on the ``mcp-analytics-clustering-schedule`` feature
flag. These tests mock the FF and the Temporal client helpers; they don't
exercise an actual Temporal server.
"""

import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.mcp_analytics.intent_clustering.constants import COORDINATOR_SCHEDULE_ID
from posthog.temporal.mcp_analytics.intent_clustering.schedule import (
    FEATURE_FLAG_KEY,
    create_intent_clustering_coordinator_schedule,
)


@pytest.fixture
def schedule_helpers():
    """Patch the four schedule helpers; yield the mocks for assertions."""
    with (
        patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.a_create_schedule", new_callable=AsyncMock
        ) as create,
        patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.a_update_schedule", new_callable=AsyncMock
        ) as update,
        patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.a_delete_schedule", new_callable=AsyncMock
        ) as delete,
        patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.a_schedule_exists", new_callable=AsyncMock
        ) as exists,
    ):
        yield {"create": create, "update": update, "delete": delete, "exists": exists}


@pytest.fixture
def mock_client():
    return object()


class TestCreateIntentClusteringCoordinatorSchedule:
    @pytest.mark.asyncio
    async def test_flag_off_no_existing_schedule_is_noop(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = False
        with patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            await create_intent_clustering_coordinator_schedule(mock_client)

        schedule_helpers["create"].assert_not_called()
        schedule_helpers["update"].assert_not_called()
        schedule_helpers["delete"].assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_off_existing_schedule_is_deleted(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = True
        with patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            await create_intent_clustering_coordinator_schedule(mock_client)

        schedule_helpers["delete"].assert_awaited_once_with(mock_client, COORDINATOR_SCHEDULE_ID)
        schedule_helpers["create"].assert_not_called()
        schedule_helpers["update"].assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_no_existing_schedule_creates(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = False
        with patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            await create_intent_clustering_coordinator_schedule(mock_client)

        schedule_helpers["create"].assert_awaited_once()
        # Assert trigger_immediately=False so first-deploy doesn't dogpile the worker.
        call_kwargs = schedule_helpers["create"].call_args.kwargs
        assert call_kwargs.get("trigger_immediately") is False
        schedule_helpers["update"].assert_not_called()
        schedule_helpers["delete"].assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_existing_schedule_updates(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = True
        with patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            await create_intent_clustering_coordinator_schedule(mock_client)

        schedule_helpers["update"].assert_awaited_once()
        schedule_helpers["create"].assert_not_called()
        schedule_helpers["delete"].assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_check_exception_defaults_to_disabled(self, mock_client, schedule_helpers) -> None:
        # Network failure / SDK bug must not crash schedule init for other modules.
        schedule_helpers["exists"].return_value = False
        with patch(
            "posthog.temporal.mcp_analytics.intent_clustering.schedule.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("PostHog FF API down"),
        ):
            await create_intent_clustering_coordinator_schedule(mock_client)

        schedule_helpers["create"].assert_not_called()
        schedule_helpers["update"].assert_not_called()


class TestFeatureFlagKeyIsStable:
    def test_flag_key_matches_documented_value(self) -> None:
        # The feature flag must be created in PostHog with this exact key.
        # Changing the key here without coordinating with the FF setup will
        # silently leave the schedule off forever.
        assert FEATURE_FLAG_KEY == "mcp-analytics-clustering-schedule"
