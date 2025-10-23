"""PostHog API client for acceptance tests."""

import json
import time
import uuid
import logging
from typing import Any, Optional

import requests
from posthoganalytics import Posthog

from .utils import get_service_url

logger = logging.getLogger(__name__)


class PostHogTestClient:
    """Client for interacting with PostHog API during tests."""

    def __init__(self, base_url: Optional[str] = None, personal_api_key: Optional[str] = None):
        self.base_url = base_url or get_service_url()
        self.session = requests.Session()

        # Set personal API key for private endpoints if provided
        if personal_api_key:
            self.session.headers.update({"Authorization": f"Bearer {personal_api_key}"})

    def create_organization(self, name: Optional[str] = None) -> dict[str, Any]:
        """Create a test organization using private API."""
        org_name = name or f"test_org_{uuid.uuid4().hex[:8]}"

        logger.info("Creating organization '%s'", org_name)
        logger.debug("POST %s/api/organizations/", self.base_url)

        response = self.session.post(f"{self.base_url}/api/organizations/", json={"name": org_name})

        logger.debug("Response status: %s", response.status_code)
        response.raise_for_status()

        result = response.json()
        logger.info("Organization created with ID: %s", result.get("id"))
        return result

    def create_project(self, organization_id: str, name: Optional[str] = None) -> dict[str, Any]:
        """Create a test project within an organization using private API."""
        project_name = name or f"test_project_{uuid.uuid4().hex[:8]}"

        logger.info("Creating project '%s' in org %s", project_name, organization_id)
        logger.debug("POST %s/api/organizations/%s/projects/", self.base_url, organization_id)

        response = self.session.post(
            f"{self.base_url}/api/organizations/{organization_id}/projects/", json={"name": project_name}
        )

        logger.debug("Response status: %s", response.status_code)
        response.raise_for_status()

        result = response.json()
        logger.info("Project created with ID: %s", result.get("id"))

        # Wait for project to be available in query API
        self._wait_for_project_ready(result.get("id"))

        return result

    def _wait_for_project_ready(self, project_id: str, timeout: int = 30) -> None:
        """Wait for project to be ready for queries."""
        logger.info("Waiting for project %s to be ready for queries...", project_id)
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # First check if the project exists via the basic project API
                project_response = self.session.get(f"{self.base_url}/api/projects/{project_id}/")
                if project_response.status_code != 200:
                    logger.debug("Project %s not accessible via API, waiting...", project_id)
                    time.sleep(1)
                    continue

                # Then try a simple HogQL query to see if the project is ready
                query_response = self.session.post(
                    f"{self.base_url}/api/environments/{project_id}/query/",
                    json={"query": {"kind": "HogQLQuery", "query": "SELECT 1 LIMIT 1"}},
                )
                if query_response.status_code == 200:
                    logger.info("Project %s is ready for queries", project_id)
                    return
                elif query_response.status_code == 404:
                    logger.debug("Project %s query endpoint not yet available, waiting...", project_id)
                else:
                    logger.debug(
                        "Project %s query returned status %s, waiting...", project_id, query_response.status_code
                    )
            except Exception as e:
                logger.debug("Project %s readiness check failed: %s, waiting...", project_id, e)

            time.sleep(1)

        logger.warning("Project %s may not be fully ready after %s seconds", project_id, timeout)

    def send_capture_event(self, api_key: str, event_data: dict[str, Any]) -> None:
        """Send an event using the PostHog Python client.

        Uses the official PostHog Python client which handles the capture endpoint.
        """
        # Extract event details
        event_name = event_data.get("event", "test_event")
        distinct_id = event_data.get("distinct_id", f"test_user_{uuid.uuid4().hex[:8]}")
        properties = event_data.get("properties", {})
        timestamp = event_data.get("timestamp")

        logger.info("Creating PostHog client instance")
        logger.debug("Host: %s", self.base_url)

        # Create PostHog client instance with the API key
        posthog_client = Posthog(api_key, host=self.base_url, debug=True)

        logger.info("Sending capture event using PostHog client")
        logger.debug("Event: %s", event_name)
        logger.debug("Distinct ID: %s", distinct_id)
        logger.debug("Properties: %s", properties)
        if timestamp:
            logger.debug("Timestamp: %s", timestamp)

        # Send event using PostHog client instance
        if timestamp:
            posthog_client.capture(
                distinct_id=distinct_id, event=event_name, properties=properties, timestamp=timestamp
            )
        else:
            posthog_client.capture(distinct_id=distinct_id, event=event_name, properties=properties)

        logger.info("Event sent via PostHog client")

        # Flush to ensure the event is sent immediately
        logger.debug("Flushing PostHog client")
        posthog_client.flush()
        logger.debug("PostHog client flushed")

        # Shutdown the client
        posthog_client.shutdown()

    def query_events_hogql(
        self, project_id: str, event_name: Optional[str] = None, distinct_id: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Query events using the HogQL query API (recommended method)."""
        # Build HogQL query
        conditions = []
        if event_name:
            conditions.append(f"event = '{event_name}'")
        if distinct_id:
            conditions.append(f"distinct_id = '{distinct_id}'")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM events {where_clause} ORDER BY timestamp DESC LIMIT {limit}"

        logger.debug("Executing HogQL query: %s", query)
        response = self.session.post(
            f"{self.base_url}/api/environments/{project_id}/query/",
            json={"refresh": "force_blocking", "query": {"kind": "HogQLQuery", "query": query}},
        )

        logger.debug("HogQL query response status: %s", response.status_code)
        response.raise_for_status()

        data = response.json()
        logger.debug("HogQL query returned %s results", len(data.get("results", [])))

        # Extract events from HogQL response
        if data.get("results"):
            # Convert HogQL results to event-like format
            columns = data.get("columns", [])
            results = []
            for row in data["results"]:
                event = {}
                for i, col in enumerate(columns):
                    if i < len(row):
                        value = row[i]
                        # Parse JSON columns (properties is returned as JSON string)
                        if col == "properties" and isinstance(value, str):
                            try:
                                value = json.loads(value)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        event[col] = value
                results.append(event)
            return results
        return []

    def wait_for_event(
        self,
        project_id: str,
        event_name: str,
        distinct_id: Optional[str] = None,
        timeout: int = 30,
        poll_interval: float = 5.0,
    ) -> Optional[dict[str, Any]]:
        """Poll for an event to appear in the query API."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Use HogQL query (recommended)
            events = self.query_events_hogql(project_id, event_name, distinct_id, limit=10)

            for event in events:
                if event.get("event") == event_name:
                    if distinct_id is None or event.get("distinct_id") == distinct_id:
                        return event

            time.sleep(poll_interval)

        return None

    def delete_project(self, project_id: str) -> None:
        """Delete a project using private API."""
        logger.info("Deleting project %s", project_id)
        logger.debug("DELETE %s/api/environments/%s/", self.base_url, project_id)

        response = self.session.delete(f"{self.base_url}/api/environments/{project_id}/")

        logger.debug("Response status: %s", response.status_code)
        response.raise_for_status()
        logger.info("Project deleted successfully")

    def delete_organization(self, organization_id: str) -> None:
        """Delete an organization using private API."""
        logger.info("Deleting organization %s", organization_id)
        logger.debug("DELETE %s/api/organizations/%s/", self.base_url, organization_id)

        response = self.session.delete(f"{self.base_url}/api/organizations/{organization_id}/")

        logger.debug("Response status: %s", response.status_code)
        response.raise_for_status()
        logger.info("Organization deleted successfully")
