"""Lifecycle events for the email thread rematch Celery tasks.

Each run emits `email_thread_rematch` with `status="started"` before any work, then one
terminal status. A worker killed by SIGKILL, an out-of-memory kill or a hard time limit
sends no terminal event, so a `started` event without a terminal event marks a lost run.
Telemetry never raises into the rematch.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final, Literal

import structlog

from posthog.ph_client import ScopedCapture, ph_scoped_capture
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

EMAIL_THREAD_REMATCH_EVENT: Final = "email_thread_rematch"

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
    base_properties: dict[str, object] = {
        "$process_person_profile": False,
        "team_id": team_id,
        "region": get_instance_region() or "unknown",
        "rematch_type": rematch_type,
        "task_id": task_id,
        "attempt": retries + 1,
        "is_retry": retries > 0,
    }
    with ph_scoped_capture() as capture:
        _capture(capture, team_id, {**base_properties, "status": "started"})
        # Flush before the work, so a worker that dies mid-run still leaves its `started` event.
        _flush(capture)
        started_at = time.monotonic()
        try:
            threads_processed = run()
        except Exception as error:
            status: EmailThreadRematchStatus = "retrying" if retries < max_retries else "failed"
            _capture_terminal(capture, team_id, base_properties, status, started_at, error=error)
            raise
        except BaseException as error:
            _capture_terminal(capture, team_id, base_properties, "interrupted", started_at, error=error)
            raise
        _capture_terminal(
            capture, team_id, base_properties, "completed", started_at, threads_processed=threads_processed
        )
        return threads_processed


def _capture_terminal(
    capture: ScopedCapture,
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
    _capture(capture, team_id, properties)


def _capture(capture: ScopedCapture, team_id: int, properties: dict[str, object]) -> None:
    try:
        capture(
            distinct_id=f"email_thread_rematch_team_{team_id}",
            event=EMAIL_THREAD_REMATCH_EVENT,
            properties=properties,
        )
    except Exception as error:
        logger.warning("email_thread_rematch_event_capture_failed", error_type=type(error).__name__)


def _flush(capture: ScopedCapture) -> None:
    try:
        capture.flush()
    except Exception as error:
        logger.warning("email_thread_rematch_event_flush_failed", error_type=type(error).__name__)
