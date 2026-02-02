"""PostHog client for acceptance tests using the official SDK."""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import requests
import structlog

# Use posthoganalytics instead of posthog to avoid conflict with local posthog/ directory
import posthoganalytics

from .config import Config
from .utils import mask_key_value

logger = structlog.get_logger(__name__)

T = TypeVar("T")


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

    def __init__(self, config: Config):
        self.config = config

        # Instantiate the official SDK client explicitly
        self._posthog = posthoganalytics.Posthog(
            config.project_api_key,
            host=config.api_host,
            debug=True,
            sync_mode=True,  # Send events synchronously for testing
        )

        logger.info(
            "PostHog SDK configured",
            sdk_host=config.api_host,
            sdk_api_key=mask_key_value(config.project_api_key),
            sdk_sync_mode=True,
            sdk_debug=True,
        )

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

    def query_event_by_uuid(
        self,
        event_uuid: str,
        timeout_seconds: int | None = None,
    ) -> CapturedEvent | None:
        """Query for an event by UUID, polling until found or timeout."""
        return self._poll_until_found(
            fetch_fn=lambda: self._fetch_event_by_uuid(event_uuid),
            description=f"event UUID '{event_uuid}'",
            timeout_seconds=timeout_seconds,
        )

    def query_person_by_distinct_id(
        self,
        distinct_id: str,
        timeout_seconds: int | None = None,
    ) -> Person | None:
        """Query for a person by distinct_id, polling until found or timeout."""
        return self._poll_until_found(
            fetch_fn=lambda: self._fetch_person_by_distinct_id(distinct_id),
            description=f"person with distinct_id '{distinct_id}'",
            timeout_seconds=timeout_seconds,
        )

    def shutdown(self) -> None:
        """Shutdown the client and flush any pending events."""
        self._posthog.shutdown()

    def _poll_until_found(
        self,
        fetch_fn: Callable[[], T | None],
        description: str,
        timeout_seconds: int | None = None,
    ) -> T | None:
        """Poll until fetch_fn returns a non-None result or timeout."""
        timeout = timeout_seconds or self.config.event_timeout_seconds
        start_time = time.time()

        while time.time() - start_time < timeout:
            result = fetch_fn()
            if result is not None:
                return result
            time.sleep(self.config.poll_interval_seconds)

        return None

    def _execute_hogql_query(self, query: str, values: dict[str, Any]) -> dict[str, Any] | None:
        """Execute a HogQL query and return the first row as a dict, or None if no results."""
        url = f"{self.config.api_host}/api/environments/{self.config.project_id}/query/"

        response = requests.post(
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
            timeout=10,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if not results:
            return None

        columns = data.get("columns", [])
        return dict(zip(columns, results[0]))

    def _fetch_event_by_uuid(self, event_uuid: str) -> CapturedEvent | None:
        """Fetch an event by UUID."""
        query = """
            SELECT uuid, event, distinct_id, properties, timestamp
            FROM events
            WHERE uuid = {event_uuid}
            LIMIT 1
        """

        row = self._execute_hogql_query(query, {"event_uuid": event_uuid})
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
