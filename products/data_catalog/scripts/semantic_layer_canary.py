#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Run Data Catalog semantic-layer canaries through the PostHog AI API."""

from __future__ import annotations

import sys
import json
import time
import shutil
import asyncio
import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

DEFAULT_HOST = "https://us.posthog.com"
DEFAULT_PROJECT_ID = 2
DEFAULT_DATASET_NAME = "semantic-layer-canaries-v1"
DEFAULT_MAX_CONCURRENCY = 3
DEFAULT_MAX_ATTEMPTS = 2
MAX_STREAM_RECONNECTS = 8
DEFAULT_TIMEOUT_SECONDS = 1_900.0
DATASET_PAGE_SIZE = 25
BROWSER_HELPER_PATH = Path(__file__).with_name("browser_session_credentials.mjs")
DEFAULT_BROWSER_PROFILE = Path(".context/semantic-layer-canary-browser")
DEFAULT_BROWSER_LOGIN_TIMEOUT_SECONDS = 600

AgentMode = Literal["product_analytics", "sql"]
AttemptStatus = Literal["completed", "failed"]
CaseStatus = Literal["completed", "failed"]
RunStatus = Literal["completed", "partial", "failed"]


class CanaryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RetryableCanaryError(CanaryError):
    pass


class PermanentCanaryError(CanaryError):
    pass


class _DatasetSummary(BaseModel):
    id: str
    name: str
    current_revision: int | None


class _DatasetPage(BaseModel):
    results: list[_DatasetSummary]


class CanaryCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    agent_mode: AgentMode = "product_analytics"


class CanaryExpectedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_metric: str | None
    expected_routing: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)


class CanaryCaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    enabled: bool


class _DatasetItem(BaseModel):
    id: str
    input: CanaryCaseInput
    expected_output: CanaryExpectedOutput
    metadata: CanaryCaseMetadata


class _DatasetItemPage(BaseModel):
    next: str | None
    results: list[_DatasetItem]


class _ConversationOpenResponse(BaseModel):
    task_id: str
    run_id: str
    trace_id: str | None
    run_status: str
    just_created_run: bool


class _TaskRunResponse(BaseModel):
    status: str


class CanaryCase(BaseModel):
    dataset_item_id: str
    case_id: str
    category: str
    question: str
    agent_mode: AgentMode
    expected_metric: str | None
    expected_routing: str
    expected_behavior: str


class DatasetSnapshot(BaseModel):
    dataset_id: str
    dataset_name: str
    revision: int
    cases: list[CanaryCase]


class CanaryRunConfig(BaseModel):
    dataset_name: str = DEFAULT_DATASET_NAME
    revision: int | None = Field(default=None, ge=1)
    run_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    case_ids: tuple[str, ...] = ()
    max_concurrency: int = Field(default=DEFAULT_MAX_CONCURRENCY, ge=1)
    max_attempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=1)


class BrowserSessionCredentials(BaseModel):
    session_id: SecretStr
    csrf_token: SecretStr


class CanaryAttemptResult(BaseModel):
    attempt: int
    status: AttemptStatus
    trace_id: str
    conversation_id: str
    task_id: str | None
    task_run_id: str | None
    task_url: str | None
    duration_ms: int
    error: str | None = None


class CanaryCaseResult(BaseModel):
    case_id: str
    category: str
    expected_metric: str | None
    expected_routing: str
    expected_behavior: str
    agent_mode: AgentMode
    status: CaseStatus
    duration_ms: int
    trace_id: str | None
    conversation_id: str | None
    task_id: str | None
    task_run_id: str | None
    task_url: str | None
    attempts: list[CanaryAttemptResult]


class CanaryRunResult(BaseModel):
    schema_version: Literal[2] = 2
    run_id: str
    project_id: int
    dataset_id: str
    dataset_name: str
    dataset_revision: int
    started_at: datetime
    completed_at: datetime
    status: RunStatus
    total_cases: int
    completed_cases: int
    failed_cases: int
    cases: list[CanaryCaseResult]


class PostHogCanaryClient:
    def __init__(
        self,
        *,
        host: str,
        project_id: int,
        browser_credentials: BrowserSessionCredentials,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.project_id = project_id
        csrf_token = browser_credentials.csrf_token.get_secret_value()
        headers = {
            "X-CSRFToken": csrf_token,
            "Origin": self.host,
            "Referer": f"{self.host}/",
        }
        cookies = {
            "sessionid": browser_credentials.session_id.get_secret_value(),
            "posthog_csrftoken": csrf_token,
        }
        self._client = httpx.AsyncClient(
            base_url=self.host,
            headers=headers,
            cookies=cookies,
            timeout=httpx.Timeout(timeout_seconds, connect=30.0),
            transport=transport,
            follow_redirects=True,
        )

    async def __aenter__(self) -> PostHogCanaryClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def load_dataset_snapshot(self, dataset_name: str, revision: int | None = None) -> DatasetSnapshot:
        dataset_response = await self._client.get(
            f"/api/environments/{self.project_id}/datasets/",
            params={"search": dataset_name, "archived": "false"},
        )
        dataset_response.raise_for_status()
        dataset_page = _DatasetPage.model_validate(dataset_response.json())
        exact_matches = [dataset for dataset in dataset_page.results if dataset.name == dataset_name]
        if len(exact_matches) != 1:
            raise PermanentCanaryError("dataset_not_found")

        dataset = exact_matches[0]
        selected_revision = revision if revision is not None else dataset.current_revision
        if selected_revision is None:
            raise PermanentCanaryError("dataset_has_no_revision")

        cases = await self._load_cases(dataset.id, selected_revision)
        return DatasetSnapshot(
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            revision=selected_revision,
            cases=cases,
        )

    async def _load_cases(self, dataset_id: str, revision: int) -> list[CanaryCase]:
        cases: list[CanaryCase] = []
        seen_case_ids: set[str] = set()
        offset = 0

        while True:
            response = await self._client.get(
                f"/api/environments/{self.project_id}/dataset_items/",
                params={
                    "dataset": dataset_id,
                    "revision": revision,
                    "archived": "false",
                    "limit": DATASET_PAGE_SIZE,
                    "offset": offset,
                },
            )
            response.raise_for_status()
            page = _DatasetItemPage.model_validate(response.json())
            for item in page.results:
                if not item.metadata.enabled:
                    continue
                if item.metadata.case_id in seen_case_ids:
                    raise PermanentCanaryError("duplicate_case_id")
                seen_case_ids.add(item.metadata.case_id)
                cases.append(
                    CanaryCase(
                        dataset_item_id=item.id,
                        case_id=item.metadata.case_id,
                        category=item.metadata.category,
                        question=item.input.question,
                        agent_mode=item.input.agent_mode,
                        expected_metric=item.expected_output.expected_metric,
                        expected_routing=item.expected_output.expected_routing,
                        expected_behavior=item.expected_output.expected_behavior,
                    )
                )
            if page.next is None:
                return cases
            if not page.results:
                raise PermanentCanaryError("invalid_dataset_pagination")
            offset += len(page.results)

    async def open_turn(
        self,
        *,
        run_id: str,
        case: CanaryCase,
        conversation_id: str,
        trace_id: str,
    ) -> _ConversationOpenResponse:
        try:
            response = await self._client.post(
                f"/api/projects/{self.project_id}/conversations/{conversation_id}/open/",
                headers={"X-POSTHOG-SESSION-ID": f"semantic-canary:{run_id}"},
                json={
                    "content": case.question,
                    "trace_id": trace_id,
                    "initial_permission_mode": "auto",
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise RetryableCanaryError("transport_error") from error

        _raise_for_api_error(response)
        try:
            opened = _ConversationOpenResponse.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError) as error:
            raise RetryableCanaryError("invalid_open_response") from error
        if opened.trace_id != trace_id:
            raise RetryableCanaryError("invalid_open_response")
        return opened

    async def wait_for_turn(self, opened: _ConversationOpenResponse) -> None:
        last_event_id: str | None = None
        stream_path = f"/api/projects/{self.project_id}/tasks/{opened.task_id}/runs/{opened.run_id}/stream/"

        for reconnect_number in range(MAX_STREAM_RECONNECTS + 1):
            headers = {"Accept": "text/event-stream"}
            if last_event_id is not None:
                headers["Last-Event-ID"] = last_event_id
            try:
                async with self._client.stream("GET", stream_path, headers=headers) as response:
                    _raise_for_api_error(response)
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise RetryableCanaryError("invalid_content_type")
                    await _consume_task_stream(response)
                    return
            except TaskStreamReconnect as reconnect:
                if reconnect.last_event_id is not None:
                    last_event_id = reconnect.last_event_id
                if reconnect_number == MAX_STREAM_RECONNECTS:
                    raise RetryableCanaryError("task_stream_reconnect_exhausted") from reconnect
            except TaskStreamEnded:
                await self._confirm_terminal_status(opened)
                return
            except CanaryError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if reconnect_number == MAX_STREAM_RECONNECTS:
                    raise RetryableCanaryError("task_stream_reconnect_exhausted") from error

    async def _confirm_terminal_status(self, opened: _ConversationOpenResponse) -> None:
        try:
            response = await self._client.get(
                f"/api/projects/{self.project_id}/tasks/{opened.task_id}/runs/{opened.run_id}/"
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise RetryableCanaryError("transport_error") from error
        _raise_for_api_error(response)
        try:
            task_run = _TaskRunResponse.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError) as error:
            raise RetryableCanaryError("invalid_task_run_response") from error
        if task_run.status == "completed":
            return
        if task_run.status in {"failed", "cancelled"}:
            raise RetryableCanaryError(f"task_run_{task_run.status}")
        raise RetryableCanaryError("missing_turn_completion")

    def task_url(self, task_id: str, task_run_id: str) -> str:
        return f"{self.host}/project/{self.project_id}/tasks/{task_id}?runId={task_run_id}"


def parse_browser_credentials(raw_credentials: str) -> BrowserSessionCredentials:
    try:
        credentials = BrowserSessionCredentials.model_validate_json(raw_credentials)
    except ValidationError as error:
        raise PermanentCanaryError("auth_required") from error
    if not credentials.session_id.get_secret_value().strip() or not credentials.csrf_token.get_secret_value().strip():
        raise PermanentCanaryError("auth_required")
    return credentials


async def load_browser_credentials(
    *,
    host: str,
    profile_path: Path,
    login: bool,
    login_timeout_seconds: int,
) -> BrowserSessionCredentials:
    node_path = shutil.which("node")
    if node_path is None:
        raise PermanentCanaryError("browser_runtime_missing")
    if not BROWSER_HELPER_PATH.is_file():
        raise PermanentCanaryError("browser_helper_missing")

    profile_path.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        node_path,
        str(BROWSER_HELPER_PATH),
        "login" if login else "cookies",
        host,
        str(profile_path),
        str(login_timeout_seconds),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    if process.returncode == 2:
        raise PermanentCanaryError("auth_required")
    if process.returncode != 0:
        raise PermanentCanaryError("browser_auth_failed")
    try:
        return parse_browser_credentials(stdout.decode())
    except UnicodeDecodeError as error:
        raise PermanentCanaryError("browser_auth_failed") from error


class TaskStreamReconnect(CanaryError):
    def __init__(self, last_event_id: str | None) -> None:
        super().__init__("task_stream_reconnect")
        self.last_event_id = last_event_id


class TaskStreamEnded(CanaryError):
    def __init__(self) -> None:
        super().__init__("task_stream_ended")


def _raise_for_api_error(response: httpx.Response) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableCanaryError(f"http_{response.status_code}")
    if response.is_error:
        raise PermanentCanaryError(f"http_{response.status_code}")


async def _consume_task_stream(response: httpx.Response) -> None:
    event_name = "message"
    event_id: str | None = None
    last_event_id: str | None = None
    data_lines: list[str] = []

    def consume_event() -> bool:
        nonlocal event_name, event_id, last_event_id, data_lines
        current_event_name = event_name
        current_data_lines = data_lines
        if event_id is not None:
            last_event_id = event_id
        event_name = "message"
        event_id = None
        data_lines = []

        if current_event_name == "end":
            raise TaskStreamReconnect(last_event_id)
        if current_event_name == "stream-end":
            raise TaskStreamEnded
        if not current_data_lines:
            return False
        try:
            payload = json.loads("\n".join(current_data_lines))
        except json.JSONDecodeError as error:
            raise RetryableCanaryError("invalid_sse_json") from error
        if not isinstance(payload, dict):
            return False
        return _is_completed_turn(payload)

    try:
        async for line in response.aiter_lines():
            if not line:
                if consume_event():
                    return
                continue
            if line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if not separator:
                continue
            value = value.removeprefix(" ")
            if field == "event":
                event_name = value
            elif field == "id":
                event_id = value
            elif field == "data":
                data_lines.append(value)
    except (httpx.TimeoutException, httpx.TransportError) as error:
        raise TaskStreamReconnect(last_event_id) from error

    if data_lines and consume_event():
        return
    raise TaskStreamReconnect(last_event_id)


def _is_completed_turn(payload: dict[str, object]) -> bool:
    payload_type = payload.get("type")
    if payload_type == "task_run_state":
        status = payload.get("status")
        if status == "completed":
            return True
        if status in {"failed", "cancelled"}:
            raise RetryableCanaryError(f"task_run_{status}")
        return False
    if payload_type == "notification":
        notification = payload.get("notification")
        return isinstance(notification, dict) and notification.get("method") == "_posthog/turn_complete"
    if payload_type != "permission_request":
        return False
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        raise PermanentCanaryError("permission_required")
    metadata = tool_call.get("_meta")
    if not isinstance(metadata, dict):
        raise PermanentCanaryError("permission_required")
    questions = metadata.get("questions")
    if metadata.get("codeToolKind") == "question" and isinstance(questions, list) and questions:
        return True
    raise PermanentCanaryError("permission_required")


async def execute_canary(
    client: PostHogCanaryClient,
    config: CanaryRunConfig,
    *,
    id_factory: Callable[[], UUID] = uuid4,
) -> CanaryRunResult:
    started_at = datetime.now(UTC)
    snapshot = await client.load_dataset_snapshot(config.dataset_name, config.revision)
    selected_cases = _select_cases(snapshot.cases, config.case_ids)
    if not selected_cases:
        raise PermanentCanaryError("no_enabled_cases")
    semaphore = asyncio.Semaphore(config.max_concurrency)

    async def execute_with_limit(case: CanaryCase) -> CanaryCaseResult:
        async with semaphore:
            return await _execute_case(client, config, case, id_factory)

    case_results = await asyncio.gather(*(execute_with_limit(case) for case in selected_cases))
    completed_cases = sum(result.status == "completed" for result in case_results)
    failed_cases = len(case_results) - completed_cases
    if failed_cases == 0:
        status: RunStatus = "completed"
    elif completed_cases == 0:
        status = "failed"
    else:
        status = "partial"

    return CanaryRunResult(
        run_id=config.run_id,
        project_id=client.project_id,
        dataset_id=snapshot.dataset_id,
        dataset_name=snapshot.dataset_name,
        dataset_revision=snapshot.revision,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        status=status,
        total_cases=len(case_results),
        completed_cases=completed_cases,
        failed_cases=failed_cases,
        cases=case_results,
    )


def _select_cases(cases: list[CanaryCase], requested_case_ids: tuple[str, ...]) -> list[CanaryCase]:
    if not requested_case_ids:
        return cases
    requested = set(requested_case_ids)
    selected = [case for case in cases if case.case_id in requested]
    missing = requested - {case.case_id for case in selected}
    if missing:
        raise PermanentCanaryError("case_not_found")
    return selected


async def _execute_case(
    client: PostHogCanaryClient,
    config: CanaryRunConfig,
    case: CanaryCase,
    id_factory: Callable[[], UUID],
) -> CanaryCaseResult:
    started_at = time.monotonic()
    attempts: list[CanaryAttemptResult] = []
    unconfirmed_conversation_id: str | None = None

    for attempt_number in range(1, config.max_attempts + 1):
        conversation_id = unconfirmed_conversation_id or str(id_factory())
        trace_id = str(id_factory())
        attempt_started_at = time.monotonic()
        opened: _ConversationOpenResponse | None = None
        try:
            opened = await client.open_turn(
                run_id=config.run_id,
                case=case,
                conversation_id=conversation_id,
                trace_id=trace_id,
            )
            await client.wait_for_turn(opened)
        except CanaryError as error:
            unconfirmed_conversation_id = conversation_id if opened is None else None
            attempts.append(
                CanaryAttemptResult(
                    attempt=attempt_number,
                    status="failed",
                    trace_id=trace_id,
                    conversation_id=conversation_id,
                    task_id=opened.task_id if opened is not None else None,
                    task_run_id=opened.run_id if opened is not None else None,
                    task_url=client.task_url(opened.task_id, opened.run_id) if opened is not None else None,
                    duration_ms=_duration_ms(attempt_started_at),
                    error=error.code,
                )
            )
            if isinstance(error, PermanentCanaryError):
                break
            continue

        attempts.append(
            CanaryAttemptResult(
                attempt=attempt_number,
                status="completed",
                trace_id=trace_id,
                conversation_id=conversation_id,
                task_id=opened.task_id,
                task_run_id=opened.run_id,
                task_url=client.task_url(opened.task_id, opened.run_id),
                duration_ms=_duration_ms(attempt_started_at),
            )
        )
        return CanaryCaseResult(
            case_id=case.case_id,
            category=case.category,
            expected_metric=case.expected_metric,
            expected_routing=case.expected_routing,
            expected_behavior=case.expected_behavior,
            agent_mode=case.agent_mode,
            status="completed",
            duration_ms=_duration_ms(started_at),
            trace_id=trace_id,
            conversation_id=conversation_id,
            task_id=opened.task_id,
            task_run_id=opened.run_id,
            task_url=client.task_url(opened.task_id, opened.run_id),
            attempts=attempts,
        )

    return CanaryCaseResult(
        case_id=case.case_id,
        category=case.category,
        expected_metric=case.expected_metric,
        expected_routing=case.expected_routing,
        expected_behavior=case.expected_behavior,
        agent_mode=case.agent_mode,
        status="failed",
        duration_ms=_duration_ms(started_at),
        trace_id=None,
        conversation_id=None,
        task_id=None,
        task_run_id=None,
        task_url=None,
        attempts=attempts,
    )


def _duration_ms(started_at: float) -> int:
    return max(0, round((time.monotonic() - started_at) * 1_000))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--revision", type=int)
    parser.add_argument("--run-id", default=str(uuid4()))
    parser.add_argument("--case", action="append", default=[], dest="case_ids")
    parser.add_argument("--max-concurrency", type=int, default=DEFAULT_MAX_CONCURRENCY)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--browser-profile", type=Path, default=DEFAULT_BROWSER_PROFILE)
    parser.add_argument("--browser-login", action="store_true")
    parser.add_argument("--browser-login-if-needed", action="store_true")
    parser.add_argument(
        "--browser-login-timeout-seconds",
        type=int,
        default=DEFAULT_BROWSER_LOGIN_TIMEOUT_SECONDS,
    )
    return parser.parse_args(argv)


async def _run_from_args(args: argparse.Namespace) -> CanaryRunResult:
    try:
        browser_credentials = await load_browser_credentials(
            host=args.host,
            profile_path=args.browser_profile,
            login=False,
            login_timeout_seconds=args.browser_login_timeout_seconds,
        )
    except PermanentCanaryError as error:
        if error.code != "auth_required" or not args.browser_login_if_needed:
            raise
        browser_credentials = await load_browser_credentials(
            host=args.host,
            profile_path=args.browser_profile,
            login=True,
            login_timeout_seconds=args.browser_login_timeout_seconds,
        )
    config = CanaryRunConfig(
        dataset_name=args.dataset_name,
        revision=args.revision,
        run_id=args.run_id,
        case_ids=tuple(args.case_ids),
        max_concurrency=args.max_concurrency,
        max_attempts=args.max_attempts,
    )
    async with PostHogCanaryClient(
        host=args.host,
        project_id=args.project_id,
        browser_credentials=browser_credentials,
        timeout_seconds=args.timeout_seconds,
    ) as client:
        return await execute_canary(client, config)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.browser_login:
            asyncio.run(
                load_browser_credentials(
                    host=args.host,
                    profile_path=args.browser_profile,
                    login=True,
                    login_timeout_seconds=args.browser_login_timeout_seconds,
                )
            )
            print(json.dumps({"status": "authenticated", "browser_profile": str(args.browser_profile)}))
            return 0
        result = asyncio.run(_run_from_args(args))
    except (CanaryError, ValidationError, httpx.HTTPError) as error:
        code = error.code if isinstance(error, CanaryError) else type(error).__name__
        print(json.dumps({"status": "error", "error": code}), file=sys.stderr)
        return 1

    output = result.model_dump_json(indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{output}\n")
    print(output)
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
