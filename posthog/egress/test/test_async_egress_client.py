from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from yarl import URL

from posthog.egress.limiter.policies import Priority
from posthog.egress.observability.observability import EgressObservability
from posthog.egress.transport.transport import AsyncEgressClient, EgressBudgetExhausted


class _StubBudgetExhausted(EgressBudgetExhausted):
    pass


class _StubAsyncEgressClient(AsyncEgressClient):
    observability = MagicMock(spec=EgressObservability, **{"normalize_endpoint.return_value": "/"})
    egress_domain = "stub"

    def __init__(self, granted: bool) -> None:
        self._granted = granted
        self.recorded_exceptions: list[str] = []

    def _standard_headers(self) -> dict[str, str]:
        return {}

    async def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return self._granted

    def _record_response(
        self, response: aiohttp.ClientResponse, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        pass

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        self.recorded_exceptions.append(url)

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


async def test_async_base_records_a_total_deadline_timeout() -> None:
    # aiohttp raises a bare TimeoutError when ClientTimeout.total expires, and only wraps the
    # connect phase into a ClientError, so catching ClientError alone loses the likeliest outage.
    client = _StubAsyncEgressClient(granted=True)
    session = _fake_session()
    session.request = AsyncMock(side_effect=TimeoutError())

    raised = False
    try:
        await client.request(session, "GET", "https://example.com", source="test", scope="scope")
    except TimeoutError:
        raised = True

    assert raised
    assert client.recorded_exceptions == ["https://example.com"]


async def test_async_base_span_records_the_final_response_host() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    client = _StubAsyncEgressClient(granted=True)
    session = _fake_session(status=503)
    session.request.return_value.url = URL("https://redirected.example.com/final")

    with patch("posthog.egress.transport.transport.tracer", provider.get_tracer("test")):
        await client.request(session, "GET", "https://example.com/start", source="test", scope="scope")

    span = exporter.get_finished_spans()[0]
    assert span.attributes is not None
    assert span.attributes["server.address"] == "redirected.example.com"
    assert span.attributes["http.response.status_code"] == 503
    assert span.status.status_code.name == "ERROR"
