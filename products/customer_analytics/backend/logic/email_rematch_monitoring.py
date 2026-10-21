"""Lifecycle events for the email thread rematch Celery tasks.

Each run emits `email_thread_rematch` with `status="started"` before any work, then one
terminal status. A worker killed by SIGKILL, an out-of-memory kill or a hard time limit
sends no terminal event, so a `started` event without a terminal event marks a lost run.
Telemetry never raises into the rematch and never waits longer than the flush timeout.
"""

from __future__ import annotations

import time
import functools
from collections.abc import Callable
from typing import Any, Final, Literal

import structlog

from posthog.cloud_utils import is_cloud
from posthog.ph_client import get_client
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

EMAIL_THREAD_REMATCH_EVENT: Final = "email_thread_rematch"
FLUSH_TIMEOUT_SECONDS: Final = 5.0

EmailThreadRematchType = Literal["full", "threads", "account_properties"]
EmailThreadRematchStatus = Literal["started", "completed", "retrying", "failed", "interrupted"]


def run_tracked_email_thread_rematch(
    *,
    team_id: int,
    rematch_type: EmailThreadRematchType,
    task_id: str | None,
    retries: int,
    max_retries: int,
    run: Callable[[], int],
) -> int:
    client = _get_client_or_none()
    base_properties: dict[str, object] = {
        "$process_person_profile": False,
        "team_id": team_id,
        "rematch_type": rematch_type,
        "task_id": task_id,
        "attempt": retries + 1,
        "is_retry": retries > 0,
    }
    # Sent before the work, so a worker that dies mid-run still leaves its `started` event.
    _send(client, team_id, {**base_properties, "status": "started"})
    started_at = time.monotonic()
    try:
        threads_processed = run()
    except Exception as error:
        status: EmailThreadRematchStatus = "retrying" if retries < max_retries else "failed"
        _send_terminal(client, team_id, base_properties, status, started_at, error=error)
        raise
    except BaseException as error:
        _send_terminal(client, team_id, base_properties, "interrupted", started_at, error=error)
        raise
    _send_terminal(client, team_id, base_properties, "completed", started_at, threads_processed=threads_processed)
    return threads_processed


@functools.cache
def _get_client() -> Any:
    # One client per worker process: a client per run registers an exit callback that
    # `shutdown()` never removes, so per-run clients would pile up for the worker's lifetime.
    client = get_client()
    if client is not None:
        # The client's region super property overrides event properties, so it must name this deployment.
        client.super_properties["region"] = get_instance_region() or "unknown"
    return client


def _get_client_or_none() -> Any:
    if not is_cloud():
        return None
    try:
        return _get_client()
    except Exception as error:
        logger.warning("email_thread_rematch_event_client_failed", error_type=type(error).__name__)
        return None


def _send_terminal(
    client: Any,
    team_id: int,
    base_properties: dict[str, object],
    status: EmailThreadRematchStatus,
    started_at: float,
    *,
    error: BaseException | None = None,
    threads_processed: int | None = None,
) -> None:
    properties: dict[str, object] = {
        **base_properties,
        "status": status,
        "duration_seconds": round(time.monotonic() - started_at, 3),
    }
    if error is not None:
        # The class name only: the message can carry customer email addresses.
        properties["error_type"] = type(error).__name__
    if threads_processed is not None:
        properties["threads_processed"] = threads_processed
    _send(client, team_id, properties)


def _send(client: Any, team_id: int, properties: dict[str, object]) -> None:
    if client is None:
        return
    try:
        client.capture(
            distinct_id=f"email_thread_rematch_team_{team_id}",
            event=EMAIL_THREAD_REMATCH_EVENT,
            properties=properties,
        )
        client.flush(timeout_seconds=FLUSH_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("email_thread_rematch_event_capture_failed", error_type=type(error).__name__)
