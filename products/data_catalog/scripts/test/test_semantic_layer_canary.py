import json
import asyncio
from collections.abc import AsyncIterator, Callable
from uuid import UUID

import pytest

import httpx

from products.data_catalog.scripts.semantic_layer_canary import (
    BrowserSessionCredentials,
    CanaryRunConfig,
    PermanentCanaryError,
    PostHogCanaryClient,
    execute_canary,
    parse_browser_credentials,
)

DATASET_ID = "11111111-1111-1111-1111-111111111111"


def _browser_credentials() -> BrowserSessionCredentials:
    return BrowserSessionCredentials(session_id="session-secret", csrf_token="csrf-secret")


def _dataset_response(*, revision: int = 7) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {
                    "id": DATASET_ID,
                    "name": "semantic-layer-canaries-v1",
                    "current_revision": revision,
                }
            ],
        },
    )


def _dataset_item(
    case_id: str,
    *,
    enabled: bool = True,
    question: str = "Show weekly widget activations.",
) -> dict[str, object]:
    return {
        "id": f"item-{case_id}",
        "input": {"question": question},
        "expected_output": {
            "expected_metric": "Weekly widget activations",
            "expected_routing": "canonical_metric",
            "expected_behavior": "Run the approved metric and summarize its output.",
        },
        "metadata": {
            "case_id": case_id,
            "category": "direct_match",
            "enabled": enabled,
        },
    }


def _items_response(items: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"count": len(items), "next": None, "previous": None, "results": items},
    )


def _open_response(*, task_id: str, task_run_id: str, trace_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "task_id": task_id,
            "run_id": task_run_id,
            "trace_id": trace_id,
            "run_status": "queued",
            "just_created_run": True,
        },
    )


def _turn_complete_response() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=('id: 1-0\ndata: {"type":"notification","notification":{"method":"_posthog/turn_complete"}}\n\n'),
    )


def _id_factory(values: list[str]) -> Callable[[], UUID]:
    identifiers = iter(UUID(value) for value in values)
    return lambda: next(identifiers)


class _DisconnectingStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'id: 123-0\ndata: {"type":"keepalive"}\n\n'
        raise httpx.RemoteProtocolError("stream disconnected")


@pytest.mark.asyncio
async def test_load_dataset_snapshot_pins_revision_and_excludes_disabled_cases() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        if request.url.path.endswith("/datasets/"):
            assert request.url.params["search"] == "semantic-layer-canaries-v1"
            return _dataset_response()

        assert request.url.path.endswith("/dataset_items/")
        assert request.url.params["dataset"] == DATASET_ID
        assert request.url.params["revision"] == "7"
        assert request.url.params["archived"] == "false"
        return _items_response([_dataset_item("enabled"), _dataset_item("disabled", enabled=False)])

    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=_browser_credentials(),
        transport=httpx.MockTransport(handler),
    ) as client:
        snapshot = await client.load_dataset_snapshot("semantic-layer-canaries-v1")

    assert snapshot.dataset_id == DATASET_ID
    assert snapshot.revision == 7
    assert [case.case_id for case in snapshot.cases] == ["enabled"]
    assert snapshot.cases[0].expected_behavior == "Run the approved metric and summarize its output."


@pytest.mark.asyncio
async def test_browser_session_auth_sends_cookies_and_csrf_without_authorization_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        assert request.headers["X-CSRFToken"] == "csrf-secret"
        assert request.headers["Origin"] == "https://us.posthog.test"
        assert request.headers["Referer"] == "https://us.posthog.test/"
        assert request.headers["Cookie"] == "sessionid=session-secret; posthog_csrftoken=csrf-secret"
        if request.url.path.endswith("/datasets/"):
            return _dataset_response()
        return _items_response([_dataset_item("enabled")])

    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=BrowserSessionCredentials(
            session_id="session-secret",
            csrf_token="csrf-secret",
        ),
        transport=httpx.MockTransport(handler),
    ) as client:
        snapshot = await client.load_dataset_snapshot("semantic-layer-canaries-v1")

    assert [case.case_id for case in snapshot.cases] == ["enabled"]


def test_parse_browser_credentials_redacts_secrets_and_rejects_missing_session() -> None:
    credentials = parse_browser_credentials('{"session_id":"session-secret","csrf_token":"csrf-secret"}')

    assert credentials.session_id.get_secret_value() == "session-secret"
    assert credentials.csrf_token.get_secret_value() == "csrf-secret"
    assert "session-secret" not in repr(credentials)
    assert "csrf-secret" not in repr(credentials)

    with pytest.raises(PermanentCanaryError, match="auth_required"):
        parse_browser_credentials('{"session_id":"","csrf_token":"csrf-secret"}')


@pytest.mark.asyncio
async def test_execute_canary_rejects_dataset_without_enabled_cases() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/datasets/"):
            return _dataset_response()
        return _items_response([_dataset_item("disabled", enabled=False)])

    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=_browser_credentials(),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(RuntimeError, match="no_enabled_cases"):
            await execute_canary(client, CanaryRunConfig())


@pytest.mark.asyncio
async def test_execute_canary_retries_with_new_correlation_ids_without_leaking_content() -> None:
    post_payloads: list[dict[str, object]] = []
    post_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/datasets/"):
            return _dataset_response()
        if request.method == "GET" and request.url.path.endswith("/dataset_items/"):
            return _items_response([_dataset_item("revenue")])
        if request.method == "GET" and "/runs/task-run-failed/stream/" in request.url.path:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'id: 1-0\ndata: {"type":"task_run_state","status":"failed","error_message":"private failure"}\n\n'
                ),
            )
        if request.method == "GET" and "/runs/task-run-completed/stream/" in request.url.path:
            return _turn_complete_response()

        post_paths.append(request.url.path)
        post_payloads.append(json.loads(request.content))
        assert request.headers["X-POSTHOG-SESSION-ID"] == "semantic-canary:run-1"
        if len(post_payloads) == 1:
            return _open_response(task_id="task-failed", task_run_id="task-run-failed", trace_id=identifiers[1])
        return _open_response(task_id="task-completed", task_run_id="task-run-completed", trace_id=identifiers[3])

    identifiers = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000004",
    ]
    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=_browser_credentials(),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await execute_canary(
            client,
            CanaryRunConfig(dataset_name="semantic-layer-canaries-v1", run_id="run-1", max_attempts=2),
            id_factory=_id_factory(identifiers),
        )

    assert post_paths == [
        f"/api/projects/2/conversations/{identifiers[0]}/open/",
        f"/api/projects/2/conversations/{identifiers[2]}/open/",
    ]
    assert post_payloads == [
        {"content": "Show weekly widget activations.", "trace_id": identifiers[1], "initial_permission_mode": "auto"},
        {"content": "Show weekly widget activations.", "trace_id": identifiers[3], "initial_permission_mode": "auto"},
    ]
    case_result = result.cases[0]
    assert case_result.status == "completed"
    assert case_result.trace_id == identifiers[3]
    assert case_result.conversation_id == identifiers[2]
    assert case_result.task_id == "task-completed"
    assert case_result.task_run_id == "task-run-completed"
    assert case_result.task_url == "https://us.posthog.test/project/2/tasks/task-completed?runId=task-run-completed"
    assert [attempt.status for attempt in case_result.attempts] == ["failed", "completed"]
    assert [attempt.task_run_id for attempt in case_result.attempts] == ["task-run-failed", "task-run-completed"]
    assert case_result.attempts[0].task_url == (
        "https://us.posthog.test/project/2/tasks/task-failed?runId=task-run-failed"
    )
    assert result.schema_version == 2
    serialized = result.model_dump_json()
    assert "Show weekly widget activations" not in serialized
    assert "private failure" not in serialized


@pytest.mark.parametrize("disconnect_kind", ["rotation", "transport"])
@pytest.mark.asyncio
async def test_execute_canary_resumes_an_open_stream_without_resending_the_question(disconnect_kind: str) -> None:
    post_payloads: list[dict[str, object]] = []
    stream_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/datasets/"):
            return _dataset_response()
        if request.method == "GET" and request.url.path.endswith("/dataset_items/"):
            return _items_response([_dataset_item("revenue")])
        if request.method == "GET":
            stream_requests.append(request)
            if len(stream_requests) == 1 and disconnect_kind == "transport":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    stream=_DisconnectingStream(),
                )
            if len(stream_requests) == 1:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    text='id: 123-0\nevent: end\ndata: {"type":"rotated"}\n\n',
                )
            return _turn_complete_response()

        post_payloads.append(json.loads(request.content))
        return _open_response(task_id="task-1", task_run_id="task-run-1", trace_id=identifiers[1])

    identifiers = [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000004",
    ]
    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=_browser_credentials(),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await execute_canary(
            client,
            CanaryRunConfig(dataset_name="semantic-layer-canaries-v1", run_id="run-1", max_attempts=2),
            id_factory=_id_factory(identifiers),
        )

    assert post_payloads == [
        {"content": "Show weekly widget activations.", "trace_id": identifiers[1], "initial_permission_mode": "auto"}
    ]
    assert [request.url.path for request in stream_requests] == [
        "/api/projects/2/tasks/task-1/runs/task-run-1/stream/",
        "/api/projects/2/tasks/task-1/runs/task-run-1/stream/",
    ]
    assert stream_requests[0].headers.get("Last-Event-ID") is None
    assert stream_requests[1].headers["Last-Event-ID"] == "123-0"
    case_result = result.cases[0]
    assert case_result.status == "completed"
    assert case_result.trace_id == identifiers[1]
    assert case_result.conversation_id == identifiers[0]
    assert case_result.task_id == "task-1"
    assert case_result.task_run_id == "task-run-1"
    assert [attempt.status for attempt in case_result.attempts] == ["completed"]


@pytest.mark.asyncio
async def test_execute_canary_accepts_an_agent_clarification_question_as_a_completed_turn() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/datasets/"):
            return _dataset_response()
        if request.url.path.endswith("/dataset_items/"):
            return _items_response([_dataset_item("ambiguous", question="How engaged are our workspaces?")])
        if request.method == "POST":
            payload = json.loads(request.content)
            return _open_response(task_id="task-1", task_run_id="task-run-1", trace_id=str(payload["trace_id"]))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'id: 1-0\ndata: {"type":"permission_request","requestId":"request-1",'
                '"toolCallId":"tool-1","options":[{"optionId":"answer","kind":"allow_once"}],'
                '"toolCall":{"toolCallId":"tool-1","_meta":{"codeToolKind":"question",'
                '"questions":[{"question":"Which engagement window?","header":"Window",'
                '"options":[{"label":"Weekly","description":"Active in the last seven days"}]}]}}}\n\n'
            ),
        )

    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=_browser_credentials(),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await execute_canary(
            client,
            CanaryRunConfig(dataset_name="semantic-layer-canaries-v1", run_id="run-clarification", max_attempts=1),
        )

    assert result.status == "completed"
    assert result.cases[0].task_run_id == "task-run-1"


@pytest.mark.asyncio
async def test_execute_canary_confirms_terminal_run_status_after_stream_end() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/datasets/"):
            return _dataset_response()
        if request.url.path.endswith("/dataset_items/"):
            return _items_response([_dataset_item("revenue")])
        if request.method == "POST":
            payload = json.loads(request.content)
            return _open_response(task_id="task-1", task_run_id="task-run-1", trace_id=str(payload["trace_id"]))
        if request.url.path.endswith("/stream/"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='event: stream-end\ndata: {"status":"complete"}\n\n',
            )
        return httpx.Response(200, json={"id": "task-run-1", "status": "completed"})

    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=_browser_credentials(),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await execute_canary(
            client,
            CanaryRunConfig(dataset_name="semantic-layer-canaries-v1", run_id="run-terminal", max_attempts=1),
        )

    assert result.status == "completed"


@pytest.mark.asyncio
async def test_execute_canary_never_exceeds_configured_concurrency() -> None:
    active_requests = 0
    maximum_active_requests = 0
    post_count = 0
    first_three_started = asyncio.Event()
    release_requests = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_requests, maximum_active_requests, post_count
        if request.method == "GET" and request.url.path.endswith("/datasets/"):
            return _dataset_response()
        if request.method == "GET" and request.url.path.endswith("/dataset_items/"):
            return _items_response([_dataset_item(f"case-{index}") for index in range(4)])

        if request.method == "POST":
            post_count += 1
            payload = json.loads(request.content)
            return _open_response(
                task_id=f"task-{post_count}",
                task_run_id=f"task-run-{post_count}",
                trace_id=str(payload["trace_id"]),
            )

        active_requests += 1
        maximum_active_requests = max(maximum_active_requests, active_requests)
        if active_requests == 3:
            first_three_started.set()
        await release_requests.wait()
        active_requests -= 1
        return _turn_complete_response()

    async with PostHogCanaryClient(
        host="https://us.posthog.test",
        project_id=2,
        browser_credentials=_browser_credentials(),
        transport=httpx.MockTransport(handler),
    ) as client:
        run_task = asyncio.create_task(
            execute_canary(
                client,
                CanaryRunConfig(
                    dataset_name="semantic-layer-canaries-v1",
                    run_id="run-2",
                    max_attempts=1,
                    max_concurrency=3,
                ),
            )
        )
        await asyncio.wait_for(first_three_started.wait(), timeout=1)
        assert post_count == 3
        release_requests.set()
        result = await run_task

    assert maximum_active_requests == 3
    assert result.completed_cases == 4
