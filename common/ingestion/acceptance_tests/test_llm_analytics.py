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

    def test_ai_endpoint_returns_200_for_valid_request(self, test_client):
        """Test that /ai endpoint returns 200 for valid multipart request."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: /ai endpoint returns 200 for valid request")
        logger.info("=" * 60)

        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            time.sleep(5)

            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test"},
            }

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
            }

            multipart_data = MultipartEncoder(fields=fields)
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project['api_token']}"}

            response = requests.post(f"{client.base_url}/ai", data=multipart_data, headers=headers)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_ai_endpoint_get_returns_405(self, test_client):
        """Test that GET requests to /ai endpoint return 405 Method Not Allowed."""
        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            response = requests.get(
                f"{client.base_url}/ai", headers={"Authorization": f"Bearer {project['api_token']}"}
            )
            assert response.status_code == 405, f"Expected 405, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_ai_endpoint_put_returns_405(self, test_client):
        """Test that PUT requests to /ai endpoint return 405 Method Not Allowed."""
        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            response = requests.put(
                f"{client.base_url}/ai", headers={"Authorization": f"Bearer {project['api_token']}"}, data="test"
            )
            assert response.status_code == 405, f"Expected 405, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_ai_endpoint_delete_returns_405(self, test_client):
        """Test that DELETE requests to /ai endpoint return 405 Method Not Allowed."""
        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            response = requests.delete(
                f"{client.base_url}/ai", headers={"Authorization": f"Bearer {project['api_token']}"}
            )
            assert response.status_code == 405, f"Expected 405, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_ai_endpoint_no_auth_returns_401(self, test_client):
        """Test that requests without authentication return 401 Unauthorized."""
        client = test_client

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test"},
        }

        fields = {
            "event": ("event.json", json.dumps(event_data), "application/json"),
        }

        multipart_data = MultipartEncoder(fields=fields)
        response = requests.post(
            f"{client.base_url}/ai", data=multipart_data, headers={"Content-Type": multipart_data.content_type}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_ai_endpoint_invalid_auth_returns_401(self, test_client):
        """Test that requests with invalid API key return 401 Unauthorized."""
        client = test_client

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test"},
        }

        fields = {
            "event": ("event.json", json.dumps(event_data), "application/json"),
        }

        multipart_data = MultipartEncoder(fields=fields)
        response = requests.post(
            f"{client.base_url}/ai",
            data=multipart_data,
            headers={"Content-Type": multipart_data.content_type, "Authorization": "Bearer invalid_key_123"},
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_ai_endpoint_wrong_content_type_returns_400(self, test_client):
        """Test that non-multipart content type returns 400 Bad Request."""
        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test"},
            }

            response = requests.post(
                f"{client.base_url}/ai", json=event_data, headers={"Authorization": f"Bearer {project['api_token']}"}
            )
            assert response.status_code == 400, f"Expected 400, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_ai_endpoint_empty_body_returns_400(self, test_client):
        """Test that empty body returns 400 Bad Request."""
        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            response = requests.post(
                f"{client.base_url}/ai", headers={"Authorization": f"Bearer {project['api_token']}"}
            )
            assert response.status_code == 400, f"Expected 400, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_multipart_parsing_with_multiple_blobs(self, test_client):
        """Test Phase 1.2: Multipart parsing with multiple blob parts."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with multiple blobs")
        logger.info("=" * 60)

        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            time.sleep(5)

            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test-multi-blob"},
            }

            # Create 3 different blobs
            input_blob = {"messages": [{"role": "user", "content": "Hello"}]}
            output_blob = {"choices": [{"message": {"content": "Hi there"}}]}
            metadata_blob = {"model_version": "1.0", "temperature": 0.7}

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
                "event.properties.$ai_input": (
                    "input.json",
                    json.dumps(input_blob),
                    "application/json",
                ),
                "event.properties.$ai_output": (
                    "output.json",
                    json.dumps(output_blob),
                    "application/json",
                ),
                "event.properties.$ai_metadata": (
                    "metadata.json",
                    json.dumps(metadata_blob),
                    "application/json",
                ),
            }

            multipart_data = MultipartEncoder(fields=fields)
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project['api_token']}"}

            response = requests.post(f"{client.base_url}/ai", data=multipart_data, headers=headers)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

            # Verify event was processed
            event = client.wait_for_event(
                project_id=project["id"], event_name="$ai_generation", distinct_id=event_data["distinct_id"], timeout=30
            )

            assert event is not None, "Event not found"
            props = event.get("properties", {})

            # Verify all blob properties were replaced with S3 URLs
            assert "$ai_input" in props and props["$ai_input"].startswith("s3://")
            assert "$ai_output" in props and props["$ai_output"].startswith("s3://")
            assert "$ai_metadata" in props and props["$ai_metadata"].startswith("s3://")

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_multipart_parsing_with_mixed_content_types(self, test_client):
        """Test Phase 1.2: Multipart parsing with mixed content types."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with mixed content types")
        logger.info("=" * 60)

        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            time.sleep(5)

            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test-mixed-types"},
            }

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
                "event.properties.$ai_json_blob": (
                    "data.json",
                    json.dumps({"type": "json"}),
                    "application/json",
                ),
                "event.properties.$ai_text_blob": (
                    "data.txt",
                    "This is plain text content",
                    "text/plain",
                ),
                "event.properties.$ai_binary_blob": (
                    "data.bin",
                    b"\x00\x01\x02\x03\x04\x05",
                    "application/octet-stream",
                ),
            }

            multipart_data = MultipartEncoder(fields=fields)
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project['api_token']}"}

            response = requests.post(f"{client.base_url}/ai", data=multipart_data, headers=headers)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_multipart_parsing_with_custom_boundary(self, test_client):
        """Test Phase 1.2: Multipart parsing with custom boundary string."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with custom boundary")
        logger.info("=" * 60)

        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            time.sleep(5)

            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test-boundary"},
            }

            # Custom boundary with special characters
            custom_boundary = f"----CustomBoundary{uuid.uuid4().hex}----"

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
                "event.properties.$ai_data": (
                    "data.json",
                    json.dumps({"boundary": "custom"}),
                    "application/json",
                ),
            }

            multipart_data = MultipartEncoder(fields=fields, boundary=custom_boundary)
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project['api_token']}"}

            response = requests.post(f"{client.base_url}/ai", data=multipart_data, headers=headers)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_multipart_parsing_with_large_blob(self, test_client):
        """Test Phase 1.2: Multipart parsing with large blob data."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with large blob")
        logger.info("=" * 60)

        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            time.sleep(5)

            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test-large"},
            }

            # Create a large JSON blob (100KB)
            large_blob = {"messages": [{"role": "user", "content": "x" * 1000} for _ in range(100)]}

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
                "event.properties.$ai_large_input": (
                    "large.json",
                    json.dumps(large_blob),
                    "application/json",
                ),
            }

            multipart_data = MultipartEncoder(fields=fields)
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project['api_token']}"}

            response = requests.post(f"{client.base_url}/ai", data=multipart_data, headers=headers)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_multipart_parsing_with_empty_blob(self, test_client):
        """Test Phase 1.2: Multipart parsing with empty blob part."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with empty blob")
        logger.info("=" * 60)

        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            time.sleep(5)

            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test-empty"},
            }

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
                "event.properties.$ai_empty": (
                    "empty.json",
                    "",  # Empty content
                    "application/json",
                ),
            }

            multipart_data = MultipartEncoder(fields=fields)
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project['api_token']}"}

            response = requests.post(f"{client.base_url}/ai", data=multipart_data, headers=headers)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])

    def test_multipart_parsing_blob_with_special_chars_in_name(self, test_client):
        """Test Phase 1.2: Multipart parsing with special characters in blob names."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with special chars in blob names")
        logger.info("=" * 60)

        client = test_client
        org = client.create_organization()
        project = client.create_project(org["id"])

        try:
            time.sleep(5)

            event_data = {
                "event": "$ai_generation",
                "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
                "properties": {"$ai_model": "test-special-names"},
            }

            fields = {
                "event": ("event.json", json.dumps(event_data), "application/json"),
                "event.properties.$ai_special": (
                    "file-with-dashes_and_underscores.json",
                    json.dumps({"test": "special"}),
                    "application/json",
                ),
            }

            multipart_data = MultipartEncoder(fields=fields)
            headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project['api_token']}"}

            response = requests.post(f"{client.base_url}/ai", data=multipart_data, headers=headers)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        finally:
            client.delete_project(project["id"])
            client.delete_organization(org["id"])
