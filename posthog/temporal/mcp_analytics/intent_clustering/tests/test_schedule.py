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
    @pytest.mark.parametrize(
        "case_id, flag_enabled, exists_returns, expected_create, expected_update, expected_delete",
        [
            # Flag OFF + no schedule → no-op.
            ("flag_off_no_existing", False, False, False, False, False),
            # Flag OFF + existing schedule → delete (kill-switch).
            ("flag_off_existing", False, True, False, False, True),
            # Flag ON + no schedule → create (with trigger_immediately=False).
            ("flag_on_no_existing", True, False, True, False, False),
            # Flag ON + existing schedule → update.
            ("flag_on_existing", True, True, False, True, False),
            # FF check raises + no schedule exists → no-op. We don't register
            # on an uncertain FF state.
            # Sentinel value None means "raise from the FF SDK".
            ("flag_check_raises_no_existing", None, False, False, False, False),
            # FF check raises + schedule EXISTS → preserve state (no delete!).
            # A transient PostHog API outage must not silently disable a
            # properly-enabled production schedule. This is the regression
            # test for the graphite-app P1 bug.
            ("flag_check_raises_preserves_existing", None, True, False, False, False),
        ],
    )
    async def test_create_intent_clustering_coordinator_schedule(
        self,
        mock_client,
        schedule_helpers,
        case_id: str,
        flag_enabled: bool | None,
        exists_returns: bool,
        expected_create: bool,
        expected_update: bool,
        expected_delete: bool,
    ) -> None:
        schedule_helpers["exists"].return_value = exists_returns
        # None sentinel = SDK raises. Otherwise return_value=flag_enabled.
        if flag_enabled is None:
            feature_enabled_patch = patch(
                "posthog.temporal.mcp_analytics.intent_clustering.schedule.posthoganalytics.feature_enabled",
                side_effect=RuntimeError("PostHog FF API down"),
            )
        else:
            feature_enabled_patch = patch(
                "posthog.temporal.mcp_analytics.intent_clustering.schedule.posthoganalytics.feature_enabled",
                return_value=flag_enabled,
            )

        with feature_enabled_patch:
            await create_intent_clustering_coordinator_schedule(mock_client)

        if expected_create:
            schedule_helpers["create"].assert_awaited_once()
            # trigger_immediately=False so first-deploy doesn't dogpile the worker.
            assert schedule_helpers["create"].call_args.kwargs.get("trigger_immediately") is False
        else:
            schedule_helpers["create"].assert_not_called()

        if expected_update:
            schedule_helpers["update"].assert_awaited_once()
        else:
            schedule_helpers["update"].assert_not_called()

        if expected_delete:
            schedule_helpers["delete"].assert_awaited_once_with(mock_client, COORDINATOR_SCHEDULE_ID)
        else:
            schedule_helpers["delete"].assert_not_called()


class TestFeatureFlagKeyIsStable:
    def test_flag_key_matches_documented_value(self) -> None:
        # The feature flag must be created in PostHog with this exact key.
        # Changing the key here without coordinating with the FF setup will
        # silently leave the schedule off forever.
        assert FEATURE_FLAG_KEY == "mcp-analytics-clustering-schedule"
