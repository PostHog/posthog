"""PostHog client for acceptance tests using the official SDK."""

import json
import time
import uuid
import logging
from dataclasses import dataclass
from typing import Any

import requests

# Use posthoganalytics instead of posthog to avoid conflict with local posthog/ directory
import posthoganalytics

from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class CapturedEvent:
    """An event retrieved from the PostHog API."""

    uuid: str
    event: str
    distinct_id: str
    properties: dict[str, Any]
    timestamp: str


class PostHogClient:
    """Client for acceptance tests using the official PostHog SDK.

    Uses the official SDK for event capture and custom code for HogQL queries
    (since the SDK doesn't support querying).
    """

    def __init__(self, config: Config):
        self.config = config

        # Configure the official SDK
        posthoganalytics.api_key = config.project_api_key
        posthoganalytics.host = config.api_host
        posthoganalytics.debug = True
        posthoganalytics.sync_mode = True  # Send events synchronously for testing

    def capture_event(
        self,
        event_name: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Send an event using the official PostHog SDK.

        Args:
            event_name: Name of the event to capture.
            distinct_id: Distinct ID of the user.
            properties: Optional event properties.

        Returns:
            The UUID of the captured event.
        """
        event_uuid = str(uuid.uuid4())

        logger.info("[capture] Sending event '%s' with UUID %s", event_name, event_uuid)

        posthoganalytics.capture(
            distinct_id=distinct_id,
            event=event_name,
            properties=properties or {},
            uuid=event_uuid,
        )

        logger.info("[capture] Event sent successfully")
        return event_uuid

    def query_event_by_uuid(
        self,
        event_uuid: str,
        timeout_seconds: int | None = None,
    ) -> CapturedEvent | None:
        """Query for an event by UUID, polling until found or timeout.

        Args:
            event_uuid: UUID of the event to find.
            timeout_seconds: Maximum time to wait for the event.
                Defaults to config.event_timeout_seconds.

        Returns:
            The found event, or None if not found within timeout.
        """
        timeout = timeout_seconds or self.config.event_timeout_seconds
        start_time = time.time()
        attempt = 0

        logger.info("[query] Polling for event UUID '%s' (timeout: %ds)", event_uuid, timeout)

        while time.time() - start_time < timeout:
            attempt += 1
            elapsed = time.time() - start_time
            logger.debug("[query] Attempt %d (%.1fs elapsed)", attempt, elapsed)

            event = self._query_event_by_uuid_once(event_uuid)
            if event:
                logger.info("[query] Event found after %.1fs (%d attempts)", time.time() - start_time, attempt)
                return event

            time.sleep(self.config.poll_interval_seconds)

        logger.warning("[query] Event not found within %ds (%d attempts)", timeout, attempt)
        return None

    def _query_event_by_uuid_once(self, event_uuid: str) -> CapturedEvent | None:
        """Execute a single HogQL query for an event by UUID."""
        query = """
            SELECT uuid, event, distinct_id, properties, timestamp
            FROM events
            WHERE uuid = {event_uuid}
            LIMIT 1
        """

        url = f"{self.config.api_host}/api/environments/{self.config.project_id}/query/"

        response = requests.post(
            url,
            json={
                "query": {
                    "kind": "HogQLQuery",
                    "query": query,
                    "values": {"event_uuid": event_uuid},
                },
                "refresh": "force_blocking",
            },
            headers={"Authorization": f"Bearer {self.config.personal_api_key}"},
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if not results:
            return None

        columns = data.get("columns", [])
        row = results[0]
        event_dict = dict(zip(columns, row))

        properties = event_dict.get("properties", {})
        if isinstance(properties, str):
            properties = json.loads(properties)

        return CapturedEvent(
            uuid=event_dict.get("uuid", ""),
            event=event_dict.get("event", ""),
            distinct_id=event_dict.get("distinct_id", ""),
            properties=properties,
            timestamp=event_dict.get("timestamp", ""),
        )

    def shutdown(self) -> None:
        """Shutdown the client and flush any pending events."""
        posthoganalytics.shutdown()
