from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.service import RPCError, RPCStatusCode

from posthog.management.commands.delete_legacy_summarization_team_schedules import find_legacy_team_schedule_ids

MODULE = "posthog.management.commands.delete_legacy_summarization_team_schedules"


class FakeScheduleIterator:
    def __init__(self, pages: list[list[str]], errors: list[RPCError] | None = None):
        self._pages = pages
        self._errors = errors or []
        self.current_page = None
        self.next_page_token = None

    async def fetch_next_page(self) -> None:
        if self._errors:
            raise self._errors.pop(0)
        self.current_page = [SimpleNamespace(id=schedule_id) for schedule_id in self._pages.pop(0)]
        self.next_page_token = b"next" if self._pages else None


def _temporal(iterator: FakeScheduleIterator) -> SimpleNamespace:
    return SimpleNamespace(list_schedules=AsyncMock(return_value=iterator))


@pytest.mark.asyncio
async def test_only_schedules_with_the_legacy_prefix_match_across_pages():
    iterator = FakeScheduleIterator(
        [["session-summarization-team-1", "session-summarization-sweep-schedule"], ["session-summarization-team-2"]]
    )

    with patch(f"{MODULE}.asyncio.sleep", AsyncMock()):
        matching, scanned = await find_legacy_team_schedule_ids(_temporal(iterator))

    assert matching == ["session-summarization-team-1", "session-summarization-team-2"]
    assert scanned == 3


@pytest.mark.asyncio
async def test_a_rate_limit_retries_the_same_page_instead_of_ending_the_scan():
    rate_limit = RPCError("namespace rate limit exceeded", RPCStatusCode.RESOURCE_EXHAUSTED, b"")
    iterator = FakeScheduleIterator([["session-summarization-team-1"]], errors=[rate_limit])

    with patch(f"{MODULE}.asyncio.sleep", AsyncMock()):
        matching, _ = await find_legacy_team_schedule_ids(_temporal(iterator))

    assert matching == ["session-summarization-team-1"]


@pytest.mark.asyncio
async def test_other_errors_stop_the_scan():
    denied = RPCError("permission denied", RPCStatusCode.PERMISSION_DENIED, b"")

    with pytest.raises(RPCError):
        await find_legacy_team_schedule_ids(_temporal(FakeScheduleIterator([[]], errors=[denied])))
