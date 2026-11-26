import dataclasses

import pytest
from unittest.mock import patch

from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.delete_teams import activities
from posthog.temporal.delete_teams.types import TeamDataActivityInputs

pytestmark = pytest.mark.asyncio

TASK_IDS = ["task-1", "task-2", "task-3"]


class FakeTaskSessionPages:
    def __init__(self) -> None:
        self.swept: list[str] = []

    def __call__(self, team_ids: list[int], *, after_task_id: str | None, limit: int, should_stop) -> str | None:
        remaining = [task_id for task_id in TASK_IDS if after_task_id is None or task_id > after_task_id]
        if not remaining:
            return None
        self.swept.append(remaining[0])
        return remaining[0]


async def _run_attempt(environment: ActivityEnvironment, pages: FakeTaskSessionPages) -> None:
    with patch("products.tasks.backend.facade.api.delete_team_task_session_storage_page", pages):
        await environment.run(
            activities.delete_task_session_storage_activity, TeamDataActivityInputs(team_ids=[1], user_id=1)
        )


async def test_the_page_limit_fails_the_attempt_and_the_retry_resumes_from_the_cursor() -> None:
    pages = FakeTaskSessionPages()
    environment = ActivityEnvironment()
    heartbeats: list[tuple] = []
    environment.on_heartbeat = lambda *details: heartbeats.append(details)

    with patch.object(activities, "TASK_SESSION_PAGES_MAX", 2):
        with pytest.raises(ApplicationError) as raised:
            await _run_attempt(environment, pages)
        assert not raised.value.non_retryable
        assert pages.swept == ["task-1", "task-2"]
        assert heartbeats[-1] == ("task-2",)

        environment.info = dataclasses.replace(environment.info, heartbeat_details=list(heartbeats[-1]))
        await _run_attempt(environment, pages)

    assert pages.swept == ["task-1", "task-2", "task-3"]
