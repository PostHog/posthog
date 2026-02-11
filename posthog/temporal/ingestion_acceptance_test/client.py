"""PostHog client for acceptance tests using the official SDK."""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Config

if TYPE_CHECKING:
    from posthoganalytics import Posthog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


def _person_has_min_timestamp(person: "Person | None", min_timestamp: float | None) -> "Person | None":
    """Return the person only if it exists and meets the minimum timestamp requirement."""
    if person is None:
        return None
    if min_timestamp is not None:
        person_timestamp = person.properties.get("$test_timestamp")
        if person_timestamp is None or person_timestamp < min_timestamp:
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
    """Client for acceptance tests using the official PostHog SDK.

    Uses the official SDK for event capture and custom code for HogQL queries
    (since the SDK doesn't support querying).
    """

    # HTTP client configuration
    HTTP_TIMEOUT_SECONDS = 30
    HTTP_RETRY_TOTAL = 3
    HTTP_RETRY_BACKOFF_FACTOR = 0.5
    # Retry on server errors only (not rate limiting - retrying immediately won't help)
    HTTP_RETRY_STATUS_FORCELIST = (500, 502, 503, 504)

    def __init__(self, config: Config, posthog_sdk: "Posthog"):
        self.config = config
        self._posthog = posthog_sdk
        self._session = self._create_http_session()
        # Store test start date for efficient event queries.
        # ClickHouse ORDER BY uses toDate(timestamp) (day granularity), so filtering by date
        # is sufficient. We subtract 1 day to handle clock skew between test machine and server.
        self._test_start_date = (datetime.now(UTC) - timedelta(days=1)).date()

    def _create_http_session(self) -> requests.Session:
        """Create an HTTP session with retry logic for transient failures."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.HTTP_RETRY_TOTAL,
            backoff_factor=self.HTTP_RETRY_BACKOFF_FACTOR,
            status_forcelist=self.HTTP_RETRY_STATUS_FORCELIST,
            allowed_methods=["GET", "POST"],
            raise_on_status=False,  # We handle status codes ourselves
            connect=self.HTTP_RETRY_TOTAL,  # Retry on connection errors
            read=self.HTTP_RETRY_TOTAL,  # Retry on read timeouts
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

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

        self._posthog.capture(
            distinct_id=distinct_id,
            event=event_name,
            properties=properties or {},
            uuid=event_uuid,
        )

        logger.info("Event captured", event_uuid=event_uuid)

        return event_uuid

    def alias(self, alias: str, distinct_id: str) -> None:
        """Create an alias linking alias to distinct_id.

        After this call, events sent to `alias` will be associated with the same
        person as `distinct_id`.
        """
        logger.info("Creating alias", alias=alias, distinct_id=distinct_id)
        self._posthog.alias(alias, distinct_id)
        logger.info("Alias created", alias=alias, distinct_id=distinct_id)

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

        self._posthog.capture(
            distinct_id=merge_into_distinct_id,
            event="$merge_dangerously",
            properties={"alias": merge_from_distinct_id},
            uuid=event_uuid,
        )

        logger.info("Merge event captured", event_uuid=event_uuid)

        return event_uuid

    def query_event_by_uuid(self, event_uuid: str) -> CapturedEvent | None:
        """Query for an event by UUID, polling until found or timeout."""
        return self._poll_until_found(
            fetch_fn=lambda: self._fetch_event_by_uuid(event_uuid),
            description=f"event UUID '{event_uuid}'",
        )

    def query_person_by_distinct_id(self, distinct_id: str, min_timestamp: float | None = None) -> Person | None:
        """Query for a person by distinct_id, polling until found or timeout.

        Args:
            distinct_id: The distinct_id to search for.
            min_timestamp: If provided, only return the person if their $test_timestamp
                property is >= this value. This helps ensure eventual consistency by
                waiting for person updates to propagate.
        """
        return self._poll_until_found(
            fetch_fn=lambda: _person_has_min_timestamp(self._fetch_person_by_distinct_id(distinct_id), min_timestamp),
            description=f"person with distinct_id '{distinct_id}'",
        )

    def query_events_by_person_id(self, person_id: str, expected_count: int) -> list[CapturedEvent] | None:
        """Query for events by person_id, polling until expected count is reached or timeout.

        Args:
            person_id: The person ID to search events for.
            expected_count: The minimum number of events expected.

        Returns:
            List of events if expected_count is reached, None if timeout.
        """
        return self._poll_until_found(
            fetch_fn=lambda: self._fetch_events_by_person_id(person_id, expected_count),
            description=f"events for person '{person_id}'",
        )

    def shutdown(self) -> None:
        """Shutdown the client and flush any pending events."""
        self._posthog.shutdown()
        self._session.close()

    # Polling configuration
    POLL_BACKOFF_FACTOR = 1.5

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
        start_time = time.time()
        current_interval = self.config.poll_interval_seconds

        while time.time() - start_time < self.config.event_timeout_seconds:
            time.sleep(current_interval)
            try:
                result = fetch_fn()
                if result is not None:
                    return result
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "Transient error during polling, will retry",
                    error=str(e),
                    error_type=type(e).__name__,
                    description=description,
                )
            current_interval = min(
                current_interval * self.POLL_BACKOFF_FACTOR,
                self.config.event_timeout_seconds - (time.time() - start_time),
            )

        logger.warning("Polling timed out", description=description, timeout_seconds=self.config.event_timeout_seconds)
        return None

    def _execute_hogql_query(self, query: str, values: dict[str, Any]) -> dict[str, Any] | None:
        """Execute a HogQL query and return the first row as a dict, or None if no results."""
        rows = self._execute_hogql_query_all(query, values)
        if not rows:
            return None
        return rows[0]

    def _execute_hogql_query_all(self, query: str, values: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute a HogQL query and return all rows as a list of dicts.

        Uses a session with automatic retry on transient HTTP errors (5xx).
        """
        url = f"{self.config.api_host}/api/projects/{self.config.project_id}/query/"

        response = self._session.post(
            url,
            json={
                "query": {
                    "kind": "HogQLQuery",
                    "query": query,
                    "values": values,
                },
                "refresh": "force_blocking",
            },
            headers={"Authorization": f"Bearer {self.config.personal_api_key}"},
            timeout=self.HTTP_TIMEOUT_SECONDS,
        )

        if response.status_code == 404:
            return []

        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        columns = data.get("columns", [])
        return [dict(zip(columns, row, strict=True)) for row in results]

    def _fetch_event_by_uuid(self, event_uuid: str) -> CapturedEvent | None:
        """Fetch an event by UUID.

        Includes a timestamp filter to benefit from ClickHouse's table partitioning
        (PARTITION BY toYYYYMM(timestamp)) and ordering (ORDER BY includes toDate(timestamp)).
        """
        query = """
            SELECT uuid, event, distinct_id, properties, timestamp
            FROM events
            WHERE uuid = {event_uuid}
              AND timestamp >= {min_timestamp}
            LIMIT 1
        """

        row = self._execute_hogql_query(
            query,
            {
                "event_uuid": event_uuid,
                "min_timestamp": self._test_start_date.isoformat(),
            },
        )
        if not row:
            return None

        properties = row.get("properties", {})
        if isinstance(properties, str):
            properties = json.loads(properties)

        return CapturedEvent(
            uuid=row.get("uuid", ""),
            event=row.get("event", ""),
            distinct_id=row.get("distinct_id", ""),
            properties=properties,
            timestamp=row.get("timestamp", ""),
        )

    def _fetch_person_by_distinct_id(self, distinct_id: str) -> Person | None:
        """Fetch a person by distinct_id."""
        query = """
            SELECT p.id, p.properties, p.created_at
            FROM persons p
            JOIN person_distinct_ids pdi ON p.id = pdi.person_id
            WHERE pdi.distinct_id = {distinct_id}
            LIMIT 1
        """

        row = self._execute_hogql_query(query, {"distinct_id": distinct_id})
        if not row:
            return None

        properties = row.get("properties", {})
        if isinstance(properties, str):
            properties = json.loads(properties)

        return Person(
            id=row.get("id", ""),
            properties=properties,
            created_at=row.get("created_at", ""),
        )

    def _fetch_events_by_person_id(self, person_id: str, expected_count: int) -> list[CapturedEvent] | None:
        """Fetch events by person_id. Returns None if fewer than expected_count events found.

        Includes a timestamp filter to benefit from ClickHouse's table partitioning
        (PARTITION BY toYYYYMM(timestamp)) and ordering (ORDER BY includes toDate(timestamp)).
        """
        query = """
            SELECT uuid, event, distinct_id, properties, timestamp
            FROM events
            WHERE person_id = {person_id}
              AND timestamp >= {min_timestamp}
            ORDER BY timestamp ASC
        """

        rows = self._execute_hogql_query_all(
            query,
            {
                "person_id": person_id,
                "min_timestamp": self._test_start_date.isoformat(),
            },
        )
        if len(rows) < expected_count:
            return None

        events = []
        for row in rows:
            properties = row.get("properties", {})
            if isinstance(properties, str):
                properties = json.loads(properties)
            events.append(
                CapturedEvent(
                    uuid=row.get("uuid", ""),
                    event=row.get("event", ""),
                    distinct_id=row.get("distinct_id", ""),
                    properties=properties,
                    timestamp=row.get("timestamp", ""),
                )
            )
        return events
