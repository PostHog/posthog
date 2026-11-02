"""Lifecycle events for the email thread matching Celery tasks.

Each run emits `email_thread_matching` with `status="started"` before any work, then one
terminal status. A worker that stops without unwinding, such as on SIGKILL, sends no
terminal event, so a `started` event without a terminal event marks a lost run.
Telemetry never raises into the matching and never waits longer than the flush timeout.
"""

from __future__ import annotations

import time
import functools
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final, Literal

import structlog
from celery import current_task

from posthog.cloud_utils import is_cloud
from posthog.ph_client import get_client
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

EMAIL_THREAD_MATCHING_EVENT: Final = "email_thread_matching"
FLUSH_TIMEOUT_SECONDS: Final = 5.0

EmailThreadMatchingType = Literal["full", "threads", "account_properties"]


@contextmanager
def track_email_thread_matching(team_id: int, matching_type: EmailThreadMatchingType) -> Iterator[None]:
    retries = current_task.request.retries or 0
    client = _get_client_or_none()
    properties: dict[str, object] = {
        "$process_person_profile": False,
        "team_id": team_id,
        "matching_type": matching_type,
        "task_id": current_task.request.id,
        "attempt": retries + 1,
    }
    # Sent before the work, so a worker that dies mid-run still leaves its `started` event.
    _send(client, team_id, {**properties, "status": "started"})
    started_at = time.monotonic()
    try:
        yield
    except Exception as error:
        status = "retrying" if retries < (current_task.max_retries or 0) else "failed"
        # The class name only: the message can carry customer email addresses.
        _send(
            client,
            team_id,
            {
                **properties,
                "status": status,
                "duration_seconds": _seconds_since(started_at),
                "error_type": type(error).__name__,
            },
        )
        raise
    _send(client, team_id, {**properties, "status": "completed", "duration_seconds": _seconds_since(started_at)})


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
        logger.warning("email_thread_matching_event_client_failed", error_type=type(error).__name__)
        return None


def _seconds_since(started_at: float) -> float:
    return round(time.monotonic() - started_at, 3)


def _send(client: Any, team_id: int, properties: dict[str, object]) -> None:
    if client is None:
        return
    try:
        client.capture(
            distinct_id=f"email_thread_matching_team_{team_id}",
            event=EMAIL_THREAD_MATCHING_EVENT,
            properties=properties,
        )
        client.flush(timeout_seconds=FLUSH_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("email_thread_matching_event_capture_failed", error_type=type(error).__name__)
