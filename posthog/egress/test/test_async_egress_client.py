from unittest.mock import AsyncMock

import aiohttp

from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import AsyncEgressClient, EgressBudgetExhausted


class _StubBudgetExhausted(EgressBudgetExhausted):
    pass


class _StubAsyncEgressClient(AsyncEgressClient):
    def __init__(self, granted: bool) -> None:
        self._granted = granted

    def _standard_headers(self) -> dict[str, str]:
        return {}

    async def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return self._granted

    def _record_response(
        self, response: aiohttp.ClientResponse, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        pass

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        pass

    def _budget_exhausted_error(self, scope: str) -> _StubBudgetExhausted:
        return _StubBudgetExhausted("denied")


def _fake_session(status: int = 200) -> AsyncMock:
    response = AsyncMock()
    response.status = status
    session = AsyncMock()
    session.request = AsyncMock(return_value=response)
    return session


async def test_async_base_raises_for_a_denied_sheddable_call() -> None:
    # Proves the denial rule the async base shares with the sync one — a BATCH call sees no exemption.
    client = _StubAsyncEgressClient(granted=False)
    session = _fake_session()

    raised = False
    try:
        await client.request(
            session, "GET", "https://example.com", source="test", scope="scope", priority=Priority.BATCH
        )
    except _StubBudgetExhausted:
        raised = True

    assert raised
    session.request.assert_not_called()


async def test_async_base_never_raises_for_a_denied_critical_call() -> None:
    client = _StubAsyncEgressClient(granted=False)
    session = _fake_session()

    await client.request(
        session, "GET", "https://example.com", source="test", scope="scope", priority=Priority.CRITICAL
    )

    session.request.assert_awaited_once()
