import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.ai.slack_app import posthog_slack_first_patrol as wf_module
from posthog.temporal.ai.slack_app.types import PostHogSlackFirstPatrolInputs

DIGEST = {"text": "t", "variant": "finding", "runs_completed": 1}


def _inputs() -> PostHogSlackFirstPatrolInputs:
    return PostHogSlackFirstPatrolInputs(
        team_id=1,
        integration_id=2,
        slack_user_id="U1",
        dm_channel_id="D1",
        thread_ts=None,
        channel_name="posthog-inbox",
        scout_config_ids=["c1"],
        provisioned_at_iso="2026-07-02T00:00:00",
    )


async def _run_with(collect_results: list) -> tuple[list[str], AsyncMock]:
    calls: list[str] = []
    remaining = list(collect_results)

    async def fake_execute(activity_fn, *, args, **kwargs):
        calls.append(activity_fn.__name__)
        if activity_fn.__name__ == "collect_first_patrol_digest_activity":
            return remaining.pop(0)
        return None

    sleep_mock = AsyncMock()
    with (
        patch.object(wf_module.workflow, "sleep", new=sleep_mock),
        patch.object(wf_module.workflow, "execute_activity", new=fake_execute),
    ):
        await wf_module.PostHogSlackFirstPatrolWorkflow().run(_inputs())
    return calls, sleep_mock


@pytest.mark.asyncio
async def test_digest_on_first_check_posts_after_initial_delay():
    calls, sleep_mock = await _run_with([DIGEST])
    assert calls == ["collect_first_patrol_digest_activity", "post_first_patrol_digest_activity"]
    assert sleep_mock.await_count == 1


@pytest.mark.asyncio
async def test_empty_first_check_retries_once_then_posts():
    calls, sleep_mock = await _run_with([None, DIGEST])
    assert calls == [
        "collect_first_patrol_digest_activity",
        "collect_first_patrol_digest_activity",
        "post_first_patrol_digest_activity",
    ]
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_nothing_to_report_after_retry_exits_silently():
    calls, sleep_mock = await _run_with([None, None])
    assert calls == ["collect_first_patrol_digest_activity", "collect_first_patrol_digest_activity"]
    assert sleep_mock.await_count == 2
