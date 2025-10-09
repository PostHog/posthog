"""LLM Analytics capture tests - tests multipart blob upload and S3 storage."""

import json
import uuid
import logging

import pytest

import requests
from requests_toolbelt import MultipartEncoder

logger = logging.getLogger(__name__)


def assert_part_details(part, expected_name, expected_length, expected_content_type, expected_content_encoding=None):
    """Assert comprehensive details about a multipart part."""
    assert part["name"] == expected_name, f"Expected part name '{expected_name}', got '{part['name']}'"
    assert part["length"] == expected_length, f"Expected part length {expected_length}, got {part['length']}"
    assert (
        part["content-type"] == expected_content_type
    ), f"Expected content-type '{expected_content_type}', got '{part['content-type']}'"
    assert (
        part["content-encoding"] == expected_content_encoding
    ), f"Expected content-encoding '{expected_content_encoding}', got '{part['content-encoding']}'"


def assert_parts_order_and_details(response_data, expected_parts):
    """Assert that parts are in the correct order and have correct details."""
    assert "accepted_parts" in response_data, "Response should contain accepted_parts"
    assert isinstance(response_data["accepted_parts"], list), "accepted_parts should be a list"

    actual_parts = response_data["accepted_parts"]
    assert len(actual_parts) == len(expected_parts), f"Expected {len(expected_parts)} parts, got {len(actual_parts)}"

    for i, (actual_part, expected_part) in enumerate(zip(actual_parts, expected_parts)):
        expected_name, expected_length, expected_content_type, expected_content_encoding = expected_part
        assert_part_details(
            actual_part, expected_name, expected_length, expected_content_type, expected_content_encoding
        )
        logger.debug(f"Part {i}: {actual_part['name']} - {actual_part['length']} bytes - {actual_part['content-type']}")


@pytest.mark.requires_posthog
@pytest.mark.usefixtures("shared_org_project")
class TestLLMAnalytics:
    """Test LLM Analytics capture flow with multipart requests and S3 storage."""

    def test_basic_ai_generation_event(self, shared_org_project):
        """Test that we can capture an $ai_generation event with blob data via multipart request."""
        logger.info("\n" + "=" * 60)
        logger.info("STARTING TEST: Basic $ai_generation Event Capture")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        project_api_key = shared_org_project["api_key"]

        # Step 1: Using shared organization and project
        logger.info("Step 1: Using shared organization and project")

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

        # Step 4: Send multipart request to /i/v0/ai endpoint
        logger.info("Step 4: Sending multipart request to /i/v0/ai endpoint")

        capture_url = f"{client.base_url}/i/v0/ai"
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

    def test_ai_endpoint_returns_200_for_valid_request(self, shared_org_project):
        """Test that /i/v0/ai endpoint returns 200 for valid multipart request."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: /i/v0/ai endpoint returns 200 for valid request")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test"},
        }

        fields = {
            "event": ("event.json", json.dumps(event_data), "application/json"),
        }

        multipart_data = MultipartEncoder(fields=fields)
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Verify response includes all expected parts with exact details
        response_data = response.json()
        event_json = json.dumps(event_data)
        expected_parts = [("event", len(event_json), "application/json", None)]
        assert_parts_order_and_details(response_data, expected_parts)

    def test_ai_endpoint_get_returns_405(self, shared_org_project):
        """Test that GET requests to /i/v0/ai endpoint return 405 Method Not Allowed."""
        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        response = requests.get(f"{client.base_url}/i/v0/ai", headers={"Authorization": f"Bearer {project_api_key}"})
        assert response.status_code == 405, f"Expected 405, got {response.status_code}"

    def test_ai_endpoint_put_returns_405(self, shared_org_project):
        """Test that PUT requests to /i/v0/ai endpoint return 405 Method Not Allowed."""
        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        response = requests.put(
            f"{client.base_url}/i/v0/ai", headers={"Authorization": f"Bearer {project_api_key}"}, data="test"
        )
        assert response.status_code == 405, f"Expected 405, got {response.status_code}"

    def test_ai_endpoint_delete_returns_405(self, shared_org_project):
        """Test that DELETE requests to /i/v0/ai endpoint return 405 Method Not Allowed."""
        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        response = requests.delete(f"{client.base_url}/i/v0/ai", headers={"Authorization": f"Bearer {project_api_key}"})
        assert response.status_code == 405, f"Expected 405, got {response.status_code}"

    def test_ai_endpoint_no_auth_returns_401(self, function_test_client):
        """Test that requests without authentication return 401 Unauthorized."""
        client = function_test_client

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
            f"{client.base_url}/i/v0/ai", data=multipart_data, headers={"Content-Type": multipart_data.content_type}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_ai_endpoint_invalid_auth_returns_401(self, function_test_client):
        """Test that requests with invalid API key return 401 Unauthorized."""
        client = function_test_client

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
            f"{client.base_url}/i/v0/ai",
            data=multipart_data,
            headers={"Content-Type": multipart_data.content_type, "Authorization": "Bearer invalid_key_123"},
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_ai_endpoint_wrong_content_type_returns_400(self, shared_org_project):
        """Test that non-multipart content type returns 400 Bad Request."""
        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test"},
        }

        response = requests.post(
            f"{client.base_url}/i/v0/ai", json=event_data, headers={"Authorization": f"Bearer {project_api_key}"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"

    def test_ai_endpoint_empty_body_returns_400(self, shared_org_project):
        """Test that empty body returns 400 Bad Request."""
        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        response = requests.post(f"{client.base_url}/i/v0/ai", headers={"Authorization": f"Bearer {project_api_key}"})
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"

    def test_multipart_parsing_with_multiple_blobs(self, shared_org_project):
        """Test Phase 1.2: Multipart parsing with multiple blob parts."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with multiple blobs")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        project_api_key = shared_org_project["api_key"]

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
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Verify response includes all expected parts with exact details
        response_data = response.json()
        event_json = json.dumps(event_data)
        input_json = json.dumps(input_blob)
        output_json = json.dumps(output_blob)
        metadata_json = json.dumps(metadata_blob)

        expected_parts = [
            ("event", len(event_json), "application/json", None),
            ("event.properties.$ai_input", len(input_json), "application/json", None),
            ("event.properties.$ai_output", len(output_json), "application/json", None),
            ("event.properties.$ai_metadata", len(metadata_json), "application/json", None),
        ]
        assert_parts_order_and_details(response_data, expected_parts)

        # Verify event was processed
        event = client.wait_for_event(
            project_id=project_id, event_name="$ai_generation", distinct_id=event_data["distinct_id"], timeout=30
        )

        assert event is not None, "Event not found"
        props = event.get("properties", {})

        # Verify all blob properties were replaced with S3 URLs
        assert "$ai_input" in props and props["$ai_input"].startswith("s3://")
        assert "$ai_output" in props and props["$ai_output"].startswith("s3://")
        assert "$ai_metadata" in props and props["$ai_metadata"].startswith("s3://")

    def test_multipart_parsing_with_mixed_content_types(self, shared_org_project):
        """Test Phase 1.2: Multipart parsing with mixed content types."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with mixed content types")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

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
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Verify response includes all expected parts with exact details
        response_data = response.json()
        event_json = json.dumps(event_data)
        json_blob = json.dumps({"type": "json"})
        text_blob = "This is plain text content"
        binary_blob = b"\x00\x01\x02\x03\x04\x05"

        expected_parts = [
            ("event", len(event_json), "application/json", None),
            ("event.properties.$ai_json_blob", len(json_blob), "application/json", None),
            ("event.properties.$ai_text_blob", len(text_blob), "text/plain", None),
            ("event.properties.$ai_binary_blob", len(binary_blob), "application/octet-stream", None),
        ]
        assert_parts_order_and_details(response_data, expected_parts)

    def test_multipart_parsing_with_custom_boundary(self, shared_org_project):
        """Test Phase 1.2: Multipart parsing with custom boundary string."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with custom boundary")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

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
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Verify response includes all expected parts with exact details
        response_data = response.json()
        event_json = json.dumps(event_data)
        data_json = json.dumps({"boundary": "custom"})

        expected_parts = [
            ("event", len(event_json), "application/json", None),
            ("event.properties.$ai_data", len(data_json), "application/json", None),
        ]
        assert_parts_order_and_details(response_data, expected_parts)

    def test_multipart_parsing_with_large_blob(self, shared_org_project):
        """Test Phase 1.2: Multipart parsing with large blob data."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with large blob")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

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
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Verify response includes all expected parts with exact details
        response_data = response.json()
        event_json = json.dumps(event_data)
        large_blob_json = json.dumps(large_blob)

        expected_parts = [
            ("event", len(event_json), "application/json", None),
            ("event.properties.$ai_large_input", len(large_blob_json), "application/json", None),
        ]
        assert_parts_order_and_details(response_data, expected_parts)

    def test_multipart_parsing_with_empty_blob(self, shared_org_project):
        """Test Phase 1.2: Multipart parsing with empty blob part."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with empty blob")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

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
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Verify response includes all expected parts with exact details
        response_data = response.json()
        event_json = json.dumps(event_data)
        empty_content = ""  # Empty content

        expected_parts = [
            ("event", len(event_json), "application/json", None),
            ("event.properties.$ai_empty", len(empty_content), "application/json", None),
        ]
        assert_parts_order_and_details(response_data, expected_parts)

    def test_multipart_parsing_blob_with_special_chars_in_name(self, shared_org_project):
        """Test Phase 1.2: Multipart parsing with special characters in blob names."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Multipart parsing with special chars in blob names")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

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
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Verify response includes all expected parts with exact details
        response_data = response.json()
        event_json = json.dumps(event_data)
        special_json = json.dumps({"test": "special"})

        expected_parts = [
            ("event", len(event_json), "application/json", None),
            ("event.properties.$ai_special", len(special_json), "application/json", None),
        ]
        assert_parts_order_and_details(response_data, expected_parts)

    def test_multipart_malformed_boundary_returns_400(self, shared_org_project):
        """Test Phase 1.3: Malformed multipart boundary returns 400 Bad Request."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Malformed multipart boundary")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test-malformed-boundary"},
        }

        # Create multipart data with malformed boundary
        fields = {
            "event": ("event.json", json.dumps(event_data), "application/json"),
        }

        # Use a malformed boundary (contains invalid characters)
        malformed_boundary = "----InvalidBoundary\x00\x01\x02----"
        multipart_data = MultipartEncoder(fields=fields, boundary=malformed_boundary)
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 400, f"Expected 400 for malformed boundary, got {response.status_code}"

    def test_multipart_missing_boundary_returns_400(self, shared_org_project):
        """Test Phase 1.3: Missing multipart boundary returns 400 Bad Request."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Missing multipart boundary")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test-missing-boundary"},
        }

        # Create multipart data but manually set invalid Content-Type without boundary
        fields = {
            "event": ("event.json", json.dumps(event_data), "application/json"),
        }

        multipart_data = MultipartEncoder(fields=fields)
        # Override Content-Type to remove boundary parameter
        headers = {
            "Content-Type": "multipart/form-data",  # Missing boundary parameter
            "Authorization": f"Bearer {project_api_key}",
        }

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 400, f"Expected 400 for missing boundary, got {response.status_code}"

    def test_multipart_corrupted_boundary_returns_400(self, shared_org_project):
        """Test Phase 1.3: Corrupted boundary in multipart data returns 400 Bad Request."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Corrupted boundary in multipart data")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test-corrupted-boundary"},
        }

        fields = {
            "event": ("event.json", json.dumps(event_data), "application/json"),
        }

        # Create valid multipart data first
        multipart_data = MultipartEncoder(fields=fields)

        # Manually corrupt the boundary in the Content-Type header
        corrupted_content_type = multipart_data.content_type.replace("boundary=", "boundary=corrupted")
        headers = {"Content-Type": corrupted_content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 400, f"Expected 400 for corrupted boundary, got {response.status_code}"

    def test_multipart_event_not_first_returns_400(self, shared_org_project):
        """Test Phase 1.3: Event part not being first returns 400 Bad Request."""
        logger.info("\n" + "=" * 60)
        logger.info("TEST: Event part not first in multipart data")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        event_data = {
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "test-event-not-first"},
        }

        # Create multipart data with blob part first, then event part
        # This should fail because event must be first
        fields = {
            "event.properties.$ai_input": (
                "input.json",
                json.dumps({"messages": [{"role": "user", "content": "test"}]}),
                "application/json",
            ),
            "event": ("event.json", json.dumps(event_data), "application/json"),
        }

        multipart_data = MultipartEncoder(fields=fields)
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(f"{client.base_url}/i/v0/ai", data=multipart_data, headers=headers)
        assert response.status_code == 400, f"Expected 400 for event not being first, got {response.status_code}"
