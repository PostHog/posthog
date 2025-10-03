"""LLM Analytics capture tests - tests multipart blob upload and S3 storage."""

import json
import time
import uuid
import logging

import pytest

import requests
from requests_toolbelt import MultipartEncoder

logger = logging.getLogger(__name__)


@pytest.mark.requires_posthog
class TestLLMAnalytics:
    """Test LLM Analytics capture flow with multipart requests and S3 storage."""

    def test_basic_ai_generation_event(self, test_client):
        """Test that we can capture an $ai_generation event with blob data via multipart request."""
        logger.info("\n" + "=" * 60)
        logger.info("STARTING TEST: Basic $ai_generation Event Capture")
        logger.info("=" * 60)

        client = test_client
        org = None
        project = None

        try:
            # Step 1: Create test organization and project
            logger.info("Step 1: Creating test organization and project")
            org = client.create_organization()
            org_id = org["id"]
            project = client.create_project(org_id)
            project_id = project["id"]
            project_api_key = project["api_token"]
            logger.info("Project created: %s", project_id)

            # Wait for project initialization
            logger.info("Waiting for project initialization")
            time.sleep(10)

            # Step 2: Prepare test event data
            logger.info("Step 2: Preparing $ai_generation event")
            distinct_id = f"test_user_{uuid.uuid4().hex[:8]}"

            event_data = {
                "event": "$ai_generation",
                "distinct_id": distinct_id,
                "properties": {
                    "$ai_model": "gpt-4",
                    "$ai_provider": "openai",
                    "$ai_completion_tokens": 150,
                    "$ai_prompt_tokens": 50,
                    "custom_property": "test_value",
                },
                "timestamp": "2024-01-15T10:30:00Z",
            }

            # Prepare blob data
            input_blob = {
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "What is the capital of France?"},
                ],
                "temperature": 0.7,
                "max_tokens": 200,
            }

            output_blob = {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "The capital of France is Paris."},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "model": "gpt-4",
                "usage": {"prompt_tokens": 50, "completion_tokens": 150, "total_tokens": 200},
            }

            # Step 3: Create multipart request
            logger.info("Step 3: Creating multipart request")

            # Create multipart encoder with proper boundary
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
                "event.properties.$ai_input": (
                    f"blob_{uuid.uuid4().hex[:8]}",
                    json.dumps(input_blob),
                    "application/json",
                ),
                "event.properties.$ai_output_choices": (
                    f"blob_{uuid.uuid4().hex[:8]}",
                    json.dumps(output_blob),
                    "application/json",
                ),
            }

            multipart_data = MultipartEncoder(fields=fields, boundary=boundary)

            # Step 4: Send multipart request to /ai endpoint
            logger.info("Step 4: Sending multipart request to /ai endpoint")

            capture_url = f"{client.base_url}/ai"
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

            logger.debug("POST %s", capture_url)
            logger.debug("Content-Type: %s", headers["Content-Type"])

            response = requests.post(capture_url, data=multipart_data, headers=headers)

            logger.debug("Response status: %s", response.status_code)
            logger.debug("Response body: %s", response.text)

            # Check if request was successful
            response.raise_for_status()
            logger.info("Multipart request sent successfully")

            # Step 5: Wait for event to appear in query API
            logger.info("Step 5: Waiting for event to be processed")
            event = client.wait_for_event(
                project_id=project_id, event_name="$ai_generation", distinct_id=distinct_id, timeout=30
            )

            # Verify event was found
            assert event is not None, "$ai_generation event not found after 30 seconds"
            logger.info("Event found in query API")
            logger.debug("Retrieved event: %s", event)

            # Step 6: Verify event properties
            logger.info("Step 6: Verifying event properties")
            assert event.get("event") == "$ai_generation"
            assert event.get("distinct_id") == distinct_id

            event_properties = event.get("properties", {})

            # Verify standard properties
            assert event_properties.get("$ai_model") == "gpt-4"
            assert event_properties.get("$ai_provider") == "openai"
            assert event_properties.get("$ai_completion_tokens") == 150
            assert event_properties.get("$ai_prompt_tokens") == 50
            assert event_properties.get("custom_property") == "test_value"

            # Verify blob properties were replaced with S3 URLs
            assert "$ai_input" in event_properties, "$ai_input property not found"
            assert "$ai_output_choices" in event_properties, "$ai_output_choices property not found"

            ai_input_url = event_properties["$ai_input"]
            ai_output_url = event_properties["$ai_output_choices"]

            logger.debug("$ai_input URL: %s", ai_input_url)
            logger.debug("$ai_output_choices URL: %s", ai_output_url)

            # Verify URLs are S3 URLs with range parameters
            assert ai_input_url.startswith("s3://"), "$ai_input should be an S3 URL"
            assert ai_output_url.startswith("s3://"), "$ai_output_choices should be an S3 URL"
            assert "range=" in ai_input_url, "$ai_input URL should contain range parameter"
            assert "range=" in ai_output_url, "$ai_output_choices URL should contain range parameter"

            # Verify URLs point to same multipart file but different ranges
            input_base = ai_input_url.split("?")[0]
            output_base = ai_output_url.split("?")[0]
            assert input_base == output_base, "Both URLs should point to same multipart file"

            logger.info("All event properties verified successfully")
            logger.info("S3 URLs generated correctly with byte ranges")
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
