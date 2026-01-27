"""PostHog API client for acceptance tests."""

import json
import time
import uuid
import logging
from dataclasses import dataclass
from typing import Any

import requests

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
    """Client for interacting with PostHog APIs during acceptance tests.

    This client is designed for acceptance testing and provides methods to:
    - Capture events via the public /capture endpoint
    - Query events via the private HogQL API
    """

    def __init__(self, config: Config):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {config.personal_api_key}"})

    def capture_event(
        self,
        event_name: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Send an event to the /capture endpoint.

        Args:
            event_name: Name of the event to capture.
            distinct_id: Distinct ID of the user.
            properties: Optional event properties.

        Returns:
            The UUID of the captured event.

        Raises:
            requests.HTTPError: If the capture request fails.
        """
        event_uuid = str(uuid.uuid4())

        payload = {
            "api_key": self.config.project_api_key,
            "event": event_name,
            "distinct_id": distinct_id,
            "properties": properties or {},
            "uuid": event_uuid,
        }

        url = f"{self.config.api_host}/capture/"
        logger.info("[capture] POST %s", url)
        logger.debug("[capture] Payload: %s", payload)

        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        logger.info("[capture] Response: %d %s", response.status_code, response.reason)
        response.raise_for_status()

        logger.info("[capture] Event UUID: %s", event_uuid)
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

        logger.info("[query_uuid] Starting poll for event UUID '%s'", event_uuid)
        logger.info("[query_uuid] Timeout: %ds, Poll interval: %.1fs", timeout, self.config.poll_interval_seconds)

        while time.time() - start_time < timeout:
            attempt += 1
            elapsed = time.time() - start_time
            logger.info("[query_uuid] Attempt %d (%.1fs elapsed)...", attempt, elapsed)

            event = self._query_event_by_uuid_once(event_uuid)
            if event:
                logger.info("[query_uuid] ✓ Event found after %.1fs (%d attempts)", time.time() - start_time, attempt)
                return event

            logger.info(
                "[query_uuid] Event not found yet, waiting %.1fs before next attempt...",
                self.config.poll_interval_seconds,
            )
            time.sleep(self.config.poll_interval_seconds)

        logger.warning(
            "[query_uuid] ✗ Event not found within %ds (%d attempts): %s",
            timeout,
            attempt,
            event_uuid,
        )
        return None

    def _query_event_by_uuid_once(self, event_uuid: str) -> CapturedEvent | None:
        """Execute a single query for an event by UUID.

        Args:
            event_uuid: UUID of the event to find.

        Returns:
            The found event, or None if not found.
        """
        query = f"""
            SELECT uuid, event, distinct_id, properties, timestamp
            FROM events
            WHERE uuid = '{event_uuid}'
            LIMIT 1
        """

        url = f"{self.config.api_host}/api/environments/{self.config.project_id}/query/"
        logger.debug("[query_uuid] POST %s", url)
        logger.debug("[query_uuid] HogQL: %s", query.strip().replace("\n", " "))

        response = self._session.post(
            url,
            json={
                "query": {"kind": "HogQLQuery", "query": query},
                "refresh": "force_blocking",
            },
        )

        logger.debug("[query_uuid] Response: %d %s", response.status_code, response.reason)

        if response.status_code == 404:
            logger.debug("[query_uuid] Project or endpoint not found")
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
