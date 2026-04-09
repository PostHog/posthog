"""PostHog client for acceptance tests using the official SDK and direct ClickHouse queries."""

import json
import time
import uuid
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

import requests
import structlog
from clickhouse_driver.errors import ErrorCodes

from posthog.clickhouse.client.execute import sync_execute
from posthog.errors import InternalCHQueryError

from .config import Config

if TYPE_CHECKING:
    from posthoganalytics import Posthog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


def _person_has_min_version(person: "Person | None", min_version: int | None) -> "Person | None":
    """Return the person only if it exists and meets the minimum version requirement."""
    if person is None:
        return None
    if min_version is not None:
        person_version = person.properties.get("$test_version")
        if person_version is None or person_version < min_version:
            return None
    return person


@dataclass
class CapturedEvent:
    """An event retrieved from the PostHog API."""

    uuid: str
    event: str
    distinct_id: str
    properties: dict[str, Any]
    timestamp: str


@dataclass
class Person:
    """A person retrieved from the PostHog API."""

    id: str
    properties: dict[str, Any]
    created_at: str


class PostHogClient:
    """Client for acceptance tests using the official PostHog SDK for capture
    and direct ClickHouse queries for verification.
    """

    # SDK capture retry configuration (the SDK's own urllib3 retries don't cover
    # POST read errors because POST is not in urllib3's default allowed_methods)
    CAPTURE_RETRY_MAX_ATTEMPTS = 5
    CAPTURE_RETRY_INITIAL_BACKOFF_SECONDS = 1.0
    CAPTURE_RETRY_BACKOFF_FACTOR = 1.3

    def __init__(self, config: Config, posthog_sdk: "Posthog"):
        self.config = config
        self._posthog = posthog_sdk
        # Store test start date for efficient event queries.
        # ClickHouse ORDER BY uses toDate(timestamp) (day granularity), so filtering by date
        # is sufficient. We subtract 1 day to handle clock skew between test machine and server.
        self._test_start_date = (datetime.now(UTC) - timedelta(days=1)).date()
        self._pending_polls: dict[int, str] = {}
        self._pending_polls_lock = threading.Lock()

    def _retry_on_error(self, fn: Callable[[], T], description: str) -> T:
        """Retry a function on transient errors with exponential backoff.

        Used for SDK capture calls where urllib3's built-in retries don't cover
        POST read errors. Retries on connection errors and timeouts only.
        No initial delay — the first attempt runs immediately. On failure, waits
        1s, 1.3s, 1.69s, 2.2s, 2.86s (~9s total) before giving up.
        """
        backoff = self.CAPTURE_RETRY_INITIAL_BACKOFF_SECONDS
        for attempt in range(self.CAPTURE_RETRY_MAX_ATTEMPTS + 1):
            try:
                return fn()
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt == self.CAPTURE_RETRY_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "Transient error, retrying",
                    description=description,
                    attempt=attempt + 1,
                    max_attempts=self.CAPTURE_RETRY_MAX_ATTEMPTS + 1,
                    next_backoff_seconds=backoff,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                time.sleep(backoff)
                backoff *= self.CAPTURE_RETRY_BACKOFF_FACTOR
        raise RuntimeError("unreachable")

    def capture_event(
        self,
        event_name: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Send an event using the official PostHog SDK."""
        event_uuid = str(uuid.uuid4())

        logger.info(
            "Capturing event",
            event_name=event_name,
            event_uuid=event_uuid,
            distinct_id=distinct_id,
            sdk_host=self.config.api_host,
        )

        all_properties = {**(properties or {}), "$ignore_sent_at": True}

        self._retry_on_error(
            lambda: self._posthog.capture(
                distinct_id=distinct_id,
                event=event_name,
                properties=all_properties,
                uuid=event_uuid,
            ),
            description=f"capture event {event_uuid}",
        )

        logger.info("Event captured", event_uuid=event_uuid)

        return event_uuid

    def alias(self, alias: str, distinct_id: str) -> str:
        """Create an alias linking alias to distinct_id.

        After this call, events sent to `alias` will be associated with the same
        person as `distinct_id`.

        Returns:
            The event UUID of the alias event.
        """
        event_uuid = str(uuid.uuid4())
        logger.info("Creating alias", alias=alias, distinct_id=distinct_id, event_uuid=event_uuid)
        self._retry_on_error(
            lambda: self._posthog.alias(alias, distinct_id, uuid=event_uuid),
            description=f"alias {alias} -> {distinct_id}",
        )
        logger.info("Alias created", alias=alias, distinct_id=distinct_id, event_uuid=event_uuid)
        return event_uuid

    def merge_dangerously(self, merge_into_distinct_id: str, merge_from_distinct_id: str) -> str:
        """Merge two persons using $merge_dangerously.

        This merges the person with `merge_from_distinct_id` INTO the person with
        `merge_into_distinct_id`. The merge_from person will cease to exist and all
        their events will be associated with merge_into.

        WARNING: This is irreversible and has no safeguards!

        Args:
            merge_into_distinct_id: The distinct_id of the person to merge INTO (survives).
            merge_from_distinct_id: The distinct_id of the person to BE merged (disappears).

        Returns:
            The event UUID of the merge event.
        """
        event_uuid = str(uuid.uuid4())

        logger.info(
            "Merging persons dangerously",
            merge_into=merge_into_distinct_id,
            merge_from=merge_from_distinct_id,
            event_uuid=event_uuid,
        )

        self._retry_on_error(
            lambda: self._posthog.capture(
                distinct_id=merge_into_distinct_id,
                event="$merge_dangerously",
                properties={"alias": merge_from_distinct_id, "$ignore_sent_at": True},
                uuid=event_uuid,
            ),
            description=f"merge dangerously {merge_from_distinct_id} -> {merge_into_distinct_id}",
        )

        logger.info("Merge event captured", event_uuid=event_uuid)

        return event_uuid

    def query_event_by_uuid(self, event_uuid: str) -> CapturedEvent | None:
        """Query for an event by UUID, polling until found or timeout."""
        logger.info("Querying for event", event_uuid=event_uuid)
        return self._poll_until_found(
            fetch_fn=lambda: self._fetch_event_by_uuid(event_uuid),
            description=f"event UUID '{event_uuid}'",
        )

    def query_person_by_distinct_id(self, distinct_id: str, min_version: int | None = None) -> Person | None:
        """Query for a person by distinct_id, polling until found or timeout.

        Args:
            distinct_id: The distinct_id to search for.
            min_version: If provided, only return the person if their $test_version
                property is >= this value. This helps ensure eventual consistency by
                waiting for person updates to propagate.
        """
        logger.info("Querying for person", distinct_id=distinct_id, min_version=min_version)
        return self._poll_until_found(
            fetch_fn=lambda: _person_has_min_version(self._fetch_person_by_distinct_id(distinct_id), min_version),
            description=f"person with distinct_id '{distinct_id}'",
        )

    def query_events_by_person_id(self, person_id: str, expected_event_uuids: set[str]) -> list[CapturedEvent] | None:
        """Query for events by person_id, polling until all expected UUIDs are found or timeout.

        Args:
            person_id: The person ID to search events for.
            expected_event_uuids: Set of event UUIDs that must all be present.

        Returns:
            List of events if all expected UUIDs are found, None if timeout.
        """
        logger.info(
            "Querying for events by person",
            person_id=person_id,
            expected_event_uuids=expected_event_uuids,
        )
        return self._poll_until_found(
            fetch_fn=lambda: self._fetch_events_by_person_id(person_id, expected_event_uuids),
            description=f"events for person '{person_id}'",
        )

    def shutdown(self) -> None:
        """Shutdown the client and flush any pending events."""
        self._posthog.shutdown()

    def pending_polls_snapshot(self) -> dict[int, str]:
        """Return a snapshot of currently active polls, keyed by thread ID."""
        with self._pending_polls_lock:
            return dict(self._pending_polls)

    # Polling configuration
    POLL_BACKOFF_FACTOR = 1.5
    POLL_MAX_INTERVAL_SECONDS = 60.0

    def _poll_until_found(
        self,
        fetch_fn: Callable[[], T | None],
        description: str,
    ) -> T | None:
        """Poll until fetch_fn returns a non-None result or timeout.

        Sleeps before each request with exponential backoff to reduce query pressure
        and increase likelihood of success on first call. Transient connection errors
        are caught and logged, allowing polling to continue.
        """
        tid = threading.get_ident()
        with self._pending_polls_lock:
            self._pending_polls[tid] = description
        start_time = time.time()
        current_interval = self.config.poll_interval_seconds
        attempt = 0

        try:
            while time.time() - start_time < self.config.event_timeout_seconds:
                attempt += 1
                time.sleep(current_interval)
                if attempt > 1:
                    elapsed = time.time() - start_time
                    logger.info(
                        "Polling attempt",
                        attempt=attempt,
                        description=description,
                        elapsed_seconds=round(elapsed, 1),
                        next_interval_seconds=round(current_interval, 1),
                    )
                try:
                    result = fetch_fn()
                except (InternalCHQueryError, EOFError, ConnectionError, OSError) as e:
                    if isinstance(e, InternalCHQueryError) and e.code != ErrorCodes.TOO_MANY_SIMULTANEOUS_QUERIES:
                        raise
                    logger.warning(
                        "Transient error during polling, will retry",
                        error=str(e),
                        error_type=type(e).__name__,
                        description=description,
                        attempt=attempt,
                    )
                    result = None
                if result is not None:
                    elapsed = time.time() - start_time
                    logger.info(
                        "Polling succeeded",
                        description=description,
                        attempt=attempt,
                        elapsed_seconds=round(elapsed, 1),
                    )
                    return result
                current_interval = min(
                    current_interval * self.POLL_BACKOFF_FACTOR,
                    self.POLL_MAX_INTERVAL_SECONDS,
                    self.config.event_timeout_seconds - (time.time() - start_time),
                )

            logger.warning(
                "Polling timed out",
                description=description,
                timeout_seconds=self.config.event_timeout_seconds,
                attempts=attempt,
            )
            return None
        finally:
            with self._pending_polls_lock:
                self._pending_polls.pop(tid, None)

    def _fetch_event_by_uuid(self, event_uuid: str) -> CapturedEvent | None:
        """Fetch an event by UUID via direct ClickHouse query.

        Includes a timestamp filter to benefit from ClickHouse's table partitioning
        (PARTITION BY toYYYYMM(timestamp)) and ordering (ORDER BY includes toDate(timestamp)).
        """
        query = """
            SELECT uuid, event, distinct_id, properties, timestamp
            FROM events
            WHERE team_id = %(team_id)s
              AND uuid = %(event_uuid)s
              AND timestamp >= %(min_timestamp)s
            LIMIT 1
        """

        rows = sync_execute(
            query,
            {
                "team_id": self.config.team_id,
                "event_uuid": event_uuid,
                "min_timestamp": self._test_start_date.isoformat(),
            },
            team_id=self.config.team_id,
        )
        if not rows:
            return None

        row = rows[0]
        properties = row[3]
        if isinstance(properties, str):
            properties = json.loads(properties)

        return CapturedEvent(
            uuid=str(row[0]),
            event=row[1],
            distinct_id=row[2],
            properties=properties,
            timestamp=str(row[4]),
        )

    def _fetch_person_by_distinct_id(self, distinct_id: str) -> Person | None:
        """Fetch a person by distinct_id via direct ClickHouse query."""
        query = """
            SELECT p.id, p.properties, p.created_at
            FROM person p
            JOIN person_distinct_id2 pdi ON p.id = pdi.person_id AND pdi.team_id = %(team_id)s
            WHERE p.team_id = %(team_id)s
              AND pdi.distinct_id = %(distinct_id)s
              AND pdi.is_deleted = 0
              AND p.is_deleted = 0
            ORDER BY p.version DESC
            LIMIT 1
        """

        rows = sync_execute(
            query,
            {"team_id": self.config.team_id, "distinct_id": distinct_id},
            team_id=self.config.team_id,
        )
        if not rows:
            return None

        row = rows[0]
        properties = row[1]
        if isinstance(properties, str):
            properties = json.loads(properties)

        return Person(
            id=str(row[0]),
            properties=properties,
            created_at=str(row[2]),
        )

    def _fetch_events_by_person_id(self, person_id: str, expected_event_uuids: set[str]) -> list[CapturedEvent] | None:
        """Fetch events by person_id. Returns None if not all expected UUIDs are found.

        Includes a timestamp filter to benefit from ClickHouse's table partitioning
        (PARTITION BY toYYYYMM(timestamp)) and ordering (ORDER BY includes toDate(timestamp)).
        """
        query = """
            SELECT uuid, event, distinct_id, properties, timestamp
            FROM events
            WHERE team_id = %(team_id)s
              AND person_id = %(person_id)s
              AND timestamp >= %(min_timestamp)s
            ORDER BY timestamp ASC
        """

        rows = sync_execute(
            query,
            {
                "team_id": self.config.team_id,
                "person_id": person_id,
                "min_timestamp": self._test_start_date.isoformat(),
            },
            team_id=self.config.team_id,
        )
        found_uuids = {str(row[0]) for row in rows}
        if not expected_event_uuids.issubset(found_uuids):
            return None

        events = []
        for row in rows:
            properties = row[3]
            if isinstance(properties, str):
                properties = json.loads(properties)
            events.append(
                CapturedEvent(
                    uuid=str(row[0]),
                    event=row[1],
                    distinct_id=row[2],
                    properties=properties,
                    timestamp=str(row[4]),
                )
            )
        return events
