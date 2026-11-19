from datetime import datetime, timedelta
from typing import Any

import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_types import GENERATION_NOT_FOUND
from posthog.temporal.common.errors import NonReportableApplicationError
from posthog.utils import ensure_utc

from products.ai_observability.backend.ai_event_lookup import fetch_generation_event

# A generation can reach `events`, where a backfill finds it, or the scheduler's Kafka consumer
# before it reaches `ai_events`, where it is read, so a miss gets two retries before it fails the
# run. Only a live reference waits between them: a backfill miss is usually an expired row.
GENERATION_NOT_FOUND_MAX_ATTEMPTS = 3
# The waits before the second and third read of a live reference. A large generation can reach
# `ai_events` well after it reaches `events`. With the scheduler's start delay, the last read runs
# about two and a half minutes after the scheduler sees the event.
GENERATION_NOT_FOUND_RETRY_DELAYS = (timedelta(seconds=30), timedelta(seconds=90))
GENERATION_NOT_FOUND_RETRY_WINDOW = sum(GENERATION_NOT_FOUND_RETRY_DELAYS, timedelta())


class GenerationNotFoundError(NonReportableApplicationError):
    """The last miss on a reference that has no ingestion to wait for.

    Only a backfill sends such a reference, and it selects candidates from `events`, which keeps
    rows longer than `ai_events`. So the row most likely aged out of `ai_events`. An evaluation
    catches this and records a skip. A caller that does not catch it fails the run, and the error
    stays out of error tracking.
    """


def as_utc_datetime(value: str | datetime) -> datetime:
    """Read a ClickHouse event timestamp, which reaches us as a naive datetime on a direct call
    and as an ISO string once Temporal has serialized it through a payload."""
    return ensure_utc(value if isinstance(value, datetime) else datetime.fromisoformat(value))


def extract_event_tools(properties: dict[str, Any]) -> Any:
    """Extract the tool catalog (`$ai_tools`) captured on the event, regardless
    of event type.

    `$ai_generation` is the canonical carrier today, but custom span/trace
    events (e.g. an agent loop's `run_summary`) may also forward the catalog,
    and the judge prompt benefits from it for any event shape. Presence of
    `$ai_tools` drives whether the Tools section renders.
    """
    return properties.get("$ai_tools")


def hydrate_event_reference(event_data: dict[str, Any]) -> dict[str, Any]:
    """Load the generation when `event_data` carries only a reference to it.

    Capture accepts an AI event up to 8 MiB while a Temporal payload is capped near 2 MiB, so a
    large generation cannot cross the workflow boundary at all. A backfill dispatcher therefore
    ships the uuid, plus the timestamp and trace id that turn the read into a point lookup on the
    ai_events sort key, and every activity that needs the body reads it here. The live scheduler
    sends the same reference, marked `awaiting_ingestion`, for an event over its size threshold.
    """
    if "properties" in event_data:
        return event_data
    raw_timestamp = event_data.get("timestamp")
    event = fetch_generation_event(
        int(event_data["team_id"]),
        str(event_data["uuid"]),
        as_utc_datetime(raw_timestamp) if raw_timestamp else None,
        event_data.get("trace_id"),
    )
    if event is None:
        attempt = temporalio.activity.info().attempt if temporalio.activity.in_activity() else None
        if attempt is not None and attempt < GENERATION_NOT_FOUND_MAX_ATTEMPTS:
            raise NonReportableApplicationError(
                "Generation not found",
                type=GENERATION_NOT_FOUND,
                next_retry_delay=GENERATION_NOT_FOUND_RETRY_DELAYS[attempt - 1]
                if event_data.get("awaiting_ingestion")
                else None,
            )
        # A live reference still fails the run and reaches error tracking: the scheduler saw the
        # event, so a miss after the retries means ingestion lost or delayed it.
        error_class = ApplicationError if event_data.get("awaiting_ingestion") else GenerationNotFoundError
        raise error_class("Generation not found", type=GENERATION_NOT_FOUND, non_retryable=True)
    return event
