import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.messaging.backfill_precalculated_events_coordinator_workflow import (
    BackfillPrecalculatedEventsCoordinatorInputs,
    EventDateCheckInputs,
    check_day_already_backfilled_activity,
)


class TestEventDateCheckInputs:
    def test_basic_construction(self):
        inputs = EventDateCheckInputs(
            team_id=1,
            condition_hashes=["hash1", "hash2"],
            date="2024-01-15",
        )
        assert inputs.team_id == 1
        assert inputs.condition_hashes == ["hash1", "hash2"]
        assert inputs.date == "2024-01-15"


class TestBackfillPrecalculatedEventsCoordinatorInputs:
    def test_properties_to_log(self):
        inputs = BackfillPrecalculatedEventsCoordinatorInputs(
            team_id=1,
            filter_storage_key="key",
            cohort_ids=[1, 2, 3],
            condition_hashes=["hash1", "hash2"],
            days_to_backfill=30,
            concurrent_workflows=5,
        )
        props = inputs.properties_to_log
        assert props["team_id"] == 1
        assert props["cohort_count"] == 3
        assert props["days_to_backfill"] == 30
        assert props["concurrent_workflows"] == 5
        assert props["condition_count"] == 2

    def test_default_concurrent_workflows(self):
        inputs = BackfillPrecalculatedEventsCoordinatorInputs(
            team_id=1,
            filter_storage_key="key",
            cohort_ids=[1],
            condition_hashes=["hash1"],
            days_to_backfill=7,
        )
        assert inputs.concurrent_workflows == 5

    def test_default_force_reprocess(self):
        inputs = BackfillPrecalculatedEventsCoordinatorInputs(
            team_id=1,
            filter_storage_key="key",
            cohort_ids=[1],
            condition_hashes=["hash1"],
            days_to_backfill=7,
        )
        assert inputs.force_reprocess is False

    def test_force_reprocess_in_properties_to_log(self):
        inputs = BackfillPrecalculatedEventsCoordinatorInputs(
            team_id=1,
            filter_storage_key="key",
            cohort_ids=[1],
            condition_hashes=["hash1"],
            days_to_backfill=7,
            force_reprocess=True,
        )
        props = inputs.properties_to_log
        assert props["force_reprocess"] is True


class TestCheckDayAlreadyBackfilledActivity:
    @pytest.mark.asyncio
    async def test_empty_condition_hashes_returns_not_backfilled(self):
        inputs = EventDateCheckInputs(
            team_id=1,
            condition_hashes=[],
            date="2024-01-15",
        )
        result = await check_day_already_backfilled_activity(inputs)
        assert result.date == "2024-01-15"
        assert result.already_backfilled is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "condition_hashes,query_return,expected_backfilled",
        [
            (["hash1", "hash2"], b"2\n", True),
            (["hash1", "hash2"], b"1\n", False),
            (["hash1"], b"0\n", False),
        ],
        ids=["all_present", "partial", "none_found"],
    )
    async def test_backfill_status_based_on_condition_count(self, condition_hashes, query_return, expected_backfilled):
        inputs = EventDateCheckInputs(
            team_id=1,
            condition_hashes=condition_hashes,
            date="2024-01-15",
        )

        mock_client = AsyncMock()
        mock_client.read_query = AsyncMock(return_value=query_return)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_events_coordinator_workflow.get_client",
            return_value=mock_client,
        ):
            result = await check_day_already_backfilled_activity(inputs)

        assert result.date == "2024-01-15"
        assert result.already_backfilled is expected_backfilled
