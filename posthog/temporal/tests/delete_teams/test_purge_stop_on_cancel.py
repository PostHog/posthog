import asyncio
import threading
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.models.team import util as team_util
from posthog.temporal.delete_teams.activities import delete_groups_activity, delete_team_persons_activity
from posthog.temporal.delete_teams.types import TeamDataActivityInputs

pytestmark = pytest.mark.asyncio

WAIT_SECONDS = 10


@pytest.mark.parametrize(
    "activity_fn,rpc,purge,finished_rpcs",
    [
        (delete_team_persons_activity, "delete_persons_batch_for_team", "_delete_persons_for_teams", []),
        (delete_groups_activity, "delete_groups_batch_for_team", "_delete_groups_for_teams", []),
        (
            delete_groups_activity,
            "delete_group_type_mappings_batch_for_team",
            "_delete_group_type_mappings_for_teams",
            ["delete_groups_batch_for_team"],
        ),
    ],
)
async def test_a_cancelled_purge_sends_no_batch_after_the_cancel(
    activity_fn: Any, rpc: str, purge: str, finished_rpcs: list[str]
) -> None:
    first_batch_sent = threading.Event()
    cancel_delivered = threading.Event()
    purge_ended = threading.Event()
    outcome: list[BaseException | None] = []

    def send_batch(request: Any, timeout: float | None = None) -> MagicMock:
        if first_batch_sent.is_set():
            return MagicMock(deleted_count=0)
        first_batch_sent.set()
        assert cancel_delivered.wait(WAIT_SECONDS)
        return MagicMock(deleted_count=1)

    client = MagicMock()
    for finished in finished_rpcs:
        getattr(client, finished).return_value = MagicMock(deleted_count=0)
    getattr(client, rpc).side_effect = send_batch
    real_purge = getattr(team_util, purge)

    def recording_purge(*args: Any, **kwargs: Any) -> None:
        try:
            real_purge(*args, **kwargs)
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)
            raise
        finally:
            purge_ended.set()

    env = ActivityEnvironment()
    with (
        patch("posthog.personhog_client.client.get_personhog_client", return_value=client),
        patch.object(team_util, purge, recording_purge),
    ):
        run = asyncio.create_task(env.run(activity_fn, TeamDataActivityInputs(team_ids=[1], user_id=7)))
        assert await asyncio.to_thread(first_batch_sent.wait, WAIT_SECONDS)
        env.cancel()
        cancel_delivered.set()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert await asyncio.to_thread(purge_ended.wait, WAIT_SECONDS)

    assert getattr(client, rpc).call_count == 1
    assert len(outcome) == 1 and isinstance(outcome[0], team_util.TeamPurgeStopped)
