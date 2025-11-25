"""Basic capture test - creates project, sends event, and verifies it."""

import uuid
import logging

logger = logging.getLogger(__name__)


class TestBasicCapture:
    """Test basic event capture flow."""

    def test_capture_and_query_event(self, test_client):
        """Test that we can capture an event and query it back."""
        logger.info("\n" + "=" * 60)
        logger.info("STARTING TEST: Basic Event Capture")
        logger.info("=" * 60)

        client = test_client

        # Create organization and project
        org = None
        project = None

        try:
            # Step 1: Create test organization
            logger.info("Step 1: Creating test organization")
            org = client.create_organization()
            org_id = org["id"]
            logger.info("Organization created: %s", org_id)

            # Step 2: Create test project
            logger.info("Step 2: Creating test project")
            project = client.create_project(org_id)
            project_id = project["id"]
            project_api_key = project["api_token"]
            logger.info("Project created: %s", project_id)

            # Step 3: Prepare test event
            logger.info("Step 3: Preparing test event")
            event_name = f"test_event_{uuid.uuid4().hex[:8]}"
            distinct_id = f"test_user_{uuid.uuid4().hex[:8]}"
            test_properties = {"test_property": "test_value", "test_number": 42, "test_bool": True}
            logger.debug("Event name: %s", event_name)
            logger.debug("Distinct ID: %s", distinct_id)
            logger.debug("Properties: %s", test_properties)

            # Step 4: Send capture event
            logger.info("Step 4: Sending event to capture endpoint")
            client.send_capture_event(
                api_key=project_api_key,
                event_data={"event": event_name, "distinct_id": distinct_id, "properties": test_properties},
            )

            logger.info("Event sent successfully")

            # Step 5: Wait for event to appear in query API
            logger.info("Step 5: Waiting for event to be processed")
            event = client.wait_for_event(
                project_id=project_id, event_name=event_name, distinct_id=distinct_id, timeout=30
            )

            # Verify event was found
            assert event is not None, f"Event {event_name} not found after 30 seconds"
            logger.info("Event found in query API")
            logger.debug("Retrieved event: %s", event)

            # Step 6: Verify event properties
            logger.info("Step 6: Verifying event properties")
            assert (
                event.get("event") == event_name
            ), f"Event name mismatch: expected {event_name}, got {event.get('event')}"
            logger.debug("Event name matches: %s", event_name)

            assert (
                event.get("distinct_id") == distinct_id
            ), f"Distinct ID mismatch: expected {distinct_id}, got {event.get('distinct_id')}"
            logger.debug("Distinct ID matches: %s", distinct_id)

            # Check if properties match
            event_properties = event.get("properties", {})
            logger.debug("Event properties: %s", event_properties)

            for key, value in test_properties.items():
                assert key in event_properties, f"Property {key} not found in event"
                assert (
                    event_properties[key] == value
                ), f"Property {key} value mismatch: expected {value}, got {event_properties[key]}"
                logger.debug("Property %s = %s", key, value)

            logger.info("All event properties verified successfully")
            logger.info("Test completed successfully")
            logger.info("=" * 60)

        finally:
            # Cleanup
            logger.info("Step 7: Cleaning up test resources")

            if project:
                try:
                    client.delete_project(project["id"])
                    logger.info("Cleaned up project: %s", project["id"])
                except Exception as e:
                    logger.exception("Failed to delete project: %s", e)

            if org:
                try:
                    client.delete_organization(org["id"])
                    logger.info("Cleaned up organization: %s", org["id"])
                except Exception as e:
                    logger.exception("Failed to delete organization: %s", e)

            logger.info("\n" + "=" * 60)
