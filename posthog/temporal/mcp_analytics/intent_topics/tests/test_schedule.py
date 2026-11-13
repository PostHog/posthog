import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import Client

from posthog.temporal.mcp_analytics.intent_topics.schedule import SCHEDULES, create_intent_topics_schedules

MODULE = "posthog.temporal.mcp_analytics.intent_topics.schedule"


@pytest.fixture
def schedule_helpers():
    with (
        patch(f"{MODULE}.a_create_schedule", new_callable=AsyncMock) as create,
        patch(f"{MODULE}.a_update_schedule", new_callable=AsyncMock) as update,
        patch(f"{MODULE}.a_delete_schedule", new_callable=AsyncMock) as delete,
        patch(f"{MODULE}.a_schedule_exists", new_callable=AsyncMock) as exists,
    ):
        yield {"create": create, "update": update, "delete": delete, "exists": exists}


def _flag(enabled: bool):  # noqa: ANN202
    return patch(f"{MODULE}._schedule_enabled", return_value=(enabled, True))


class TestCreateIntentTopicsSchedules:
    @pytest.mark.asyncio
    async def test_flag_off_registers_nothing(self, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = False

        with _flag(False):
            await create_intent_topics_schedules(MagicMock(spec=Client))

        schedule_helpers["create"].assert_not_called()
        schedule_helpers["update"].assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("enabled", [True, False])
    async def test_a_temporal_error_never_escapes_into_the_shared_schedule_setup(
        self, schedule_helpers, enabled: bool
    ) -> None:
        # Every product's schedules are set up in one task group, so an error raised here would cancel the rest.
        schedule_helpers["exists"].side_effect = RuntimeError("temporal unavailable")

        with _flag(enabled):
            await create_intent_topics_schedules(MagicMock(spec=Client))

    @pytest.mark.asyncio
    async def test_one_failing_schedule_does_not_stop_the_others(self, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = False
        schedule_helpers["create"].side_effect = [RuntimeError("temporal unavailable"), None, None]

        with _flag(True):
            await create_intent_topics_schedules(MagicMock(spec=Client))

        assert schedule_helpers["create"].await_count == len(SCHEDULES)
