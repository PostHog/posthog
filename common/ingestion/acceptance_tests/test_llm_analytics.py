"""LLM Analytics capture tests - tests multipart blob upload and S3 storage."""

import gzip
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


@pytest.mark.usefixtures("shared_org_project")
class TestLLMAnalytics:
    """Test LLM Analytics capture flow with multipart requests and S3 storage."""

    # ============================================================================
    # PHASE 1: HTTP ENDPOINT
    # ============================================================================

    # ----------------------------------------------------------------------------
    # Scenario 1.1: Event Processing Verification
    # ----------------------------------------------------------------------------

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
        event_uuid = str(uuid.uuid4())

        event_data = {
            "uuid": event_uuid,
            "event": "$ai_generation",
            "distinct_id": distinct_id,
            "timestamp": "2024-01-15T10:30:00Z",
            "properties": {
                "$ai_model": "gpt-4",
                "$ai_provider": "openai",
                "$ai_completion_tokens": 150,
                "$ai_prompt_tokens": 50,
                "custom_property": "test_value",
            },
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
            "event": ("event", json.dumps(event_data), "application/json"),
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

        # Verify response contains accepted parts
        response_data = response.json()
        assert "accepted_parts" in response_data
        accepted_parts = response_data["accepted_parts"]
        assert len(accepted_parts) == 3, f"Expected 3 parts, got {len(accepted_parts)}"

        # Verify each part has correct details
        event_json = json.dumps(event_data)
        input_json = json.dumps(input_blob)
        output_json = json.dumps(output_blob)

        assert accepted_parts[0]["name"] == "event"
        assert accepted_parts[0]["length"] == len(event_json)
        assert accepted_parts[0]["content-type"] == "application/json"

        assert accepted_parts[1]["name"] == "event.properties.$ai_input"
        assert accepted_parts[1]["length"] == len(input_json)
        assert accepted_parts[1]["content-type"] == "application/json"

        assert accepted_parts[2]["name"] == "event.properties.$ai_output_choices"
        assert accepted_parts[2]["length"] == len(output_json)
        assert accepted_parts[2]["content-type"] == "application/json"

        logger.info("Response validation successful: all parts accepted with correct lengths")

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

    def test_ai_generation_event_with_separate_properties(self, shared_org_project):
        """Test $ai_generation event with properties in a separate multipart part."""
        logger.info("\n" + "=" * 60)
        logger.info("STARTING TEST: $ai_generation Event with Separate Properties")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        project_api_key = shared_org_project["api_key"]

        logger.info("Step 1: Using shared organization and project")

        logger.info("Step 2: Preparing $ai_generation event with separate properties")
        distinct_id = f"test_user_{uuid.uuid4().hex[:8]}"
        event_uuid = str(uuid.uuid4())

        event_data = {
            "uuid": event_uuid,
            "event": "$ai_generation",
            "distinct_id": distinct_id,
            "timestamp": "2024-01-15T10:30:00Z",
        }

        properties_data = {
            "$ai_model": "gpt-3.5-turbo",
            "$ai_provider": "openai",
            "$ai_completion_tokens": 100,
            "$ai_prompt_tokens": 25,
            "custom_property": "separate_test",
        }

        input_blob = {
            "messages": [
                {"role": "user", "content": "Tell me a joke."},
            ],
            "temperature": 0.9,
        }

        output_blob = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Why did the chicken cross the road? To get to the other side!",
                    },
                    "finish_reason": "stop",
                }
            ],
        }

        logger.info("Step 3: Creating multipart request with separate properties part")
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        fields = {
            "event": ("event", json.dumps(event_data), "application/json"),
            "event.properties": ("event.properties", json.dumps(properties_data), "application/json"),
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

        logger.info("Step 4: Sending multipart request to /i/v0/ai endpoint")
        capture_url = f"{client.base_url}/i/v0/ai"
        headers = {"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {project_api_key}"}

        response = requests.post(capture_url, data=multipart_data, headers=headers)
        response.raise_for_status()
        logger.info("Multipart request sent successfully")

        # Verify response contains accepted parts
        response_data = response.json()
        assert "accepted_parts" in response_data
        accepted_parts = response_data["accepted_parts"]
        assert len(accepted_parts) == 4, f"Expected 4 parts, got {len(accepted_parts)}"

        # Verify each part has correct details
        event_json = json.dumps(event_data)
        properties_json = json.dumps(properties_data)
        input_json = json.dumps(input_blob)
        output_json = json.dumps(output_blob)

        assert accepted_parts[0]["name"] == "event"
        assert accepted_parts[0]["length"] == len(event_json)
        assert accepted_parts[0]["content-type"] == "application/json"

        assert accepted_parts[1]["name"] == "event.properties"
        assert accepted_parts[1]["length"] == len(properties_json)
        assert accepted_parts[1]["content-type"] == "application/json"

        assert accepted_parts[2]["name"] == "event.properties.$ai_input"
        assert accepted_parts[2]["length"] == len(input_json)
        assert accepted_parts[2]["content-type"] == "application/json"

        assert accepted_parts[3]["name"] == "event.properties.$ai_output_choices"
        assert accepted_parts[3]["length"] == len(output_json)
        assert accepted_parts[3]["content-type"] == "application/json"

        logger.info("Response validation successful: all parts accepted with correct lengths")

        logger.info("Step 5: Waiting for event to be processed")
        event = client.wait_for_event(
            project_id=project_id, event_name="$ai_generation", distinct_id=distinct_id, timeout=30
        )

        assert event is not None, "$ai_generation event not found after 30 seconds"
        logger.info("Event found in query API")

        logger.info("Step 6: Verifying event properties")
        assert event.get("event") == "$ai_generation"
        assert event.get("distinct_id") == distinct_id

        event_properties = event.get("properties", {})

        assert event_properties.get("$ai_model") == "gpt-3.5-turbo"
        assert event_properties.get("$ai_provider") == "openai"
        assert event_properties.get("$ai_completion_tokens") == 100
        assert event_properties.get("$ai_prompt_tokens") == 25
        assert event_properties.get("custom_property") == "separate_test"

        assert "$ai_input" in event_properties
        assert "$ai_output_choices" in event_properties

        ai_input_url = event_properties["$ai_input"]
        ai_output_url = event_properties["$ai_output_choices"]

        assert ai_input_url.startswith("s3://")
        assert ai_output_url.startswith("s3://")
        assert "range=" in ai_input_url
        assert "range=" in ai_output_url

        input_base = ai_input_url.split("?")[0]
        output_base = ai_output_url.split("?")[0]
        assert input_base == output_base

        logger.info("All event properties verified successfully")
        logger.info("Separate properties part handled correctly")
        logger.info("Test completed successfully")
        logger.info("=" * 60)

    def test_all_accepted_ai_event_types(self, shared_org_project):
        """Test that all six accepted AI event types are successfully captured and stored."""
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        api_key = shared_org_project["api_key"]

        base_distinct_id = f"user_{uuid.uuid4()}"

        # Define all event types with their specific properties
        events_to_test = [
            {
                "event_type": "$ai_generation",
                "distinct_id": f"{base_distinct_id}_generation",
                "properties": {
                    "$ai_model": "test-model",
                    "$ai_provider": "test-provider",
                    "$ai_input_tokens": 100,
                    "$ai_output_tokens": 50,
                },
            },
            {
                "event_type": "$ai_trace",
                "distinct_id": f"{base_distinct_id}_trace",
                "properties": {
                    "$ai_model": "test-model",
                    "$ai_provider": "test-provider",
                    "$ai_trace_id": str(uuid.uuid4()),
                },
            },
            {
                "event_type": "$ai_span",
                "distinct_id": f"{base_distinct_id}_span",
                "properties": {
                    "$ai_model": "test-model",
                    "$ai_provider": "test-provider",
                    "$ai_trace_id": str(uuid.uuid4()),
                    "$ai_span_id": str(uuid.uuid4()),
                },
            },
            {
                "event_type": "$ai_embedding",
                "distinct_id": f"{base_distinct_id}_embedding",
                "properties": {
                    "$ai_model": "test-model",
                    "$ai_provider": "test-provider",
                    "$ai_input_tokens": 75,
                },
            },
            {
                "event_type": "$ai_metric",
                "distinct_id": f"{base_distinct_id}_metric",
                "properties": {
                    "$ai_model": "test-model",
                    "$ai_provider": "test-provider",
                    "$ai_metric_type": "latency",
                    "$ai_metric_value": 1.23,
                },
            },
            {
                "event_type": "$ai_feedback",
                "distinct_id": f"{base_distinct_id}_feedback",
                "properties": {
                    "$ai_model": "test-model",
                    "$ai_provider": "test-provider",
                    "$ai_feedback_score": 5,
                    "$ai_feedback_comment": "Great response",
                },
            },
        ]

        # Send all events
        for event_spec in events_to_test:
            event_type = event_spec["event_type"]
            distinct_id = event_spec["distinct_id"]
            logger.info(f"Sending {event_type} event")

            event_data = {
                "uuid": str(uuid.uuid4()),
                "event": event_type,
                "distinct_id": distinct_id,
                "$set": {"test_user": True, "event_type_test": event_type},
            }

            fields = {
                "event": ("event", json.dumps(event_data), "application/json"),
                "event.properties": ("event.properties", json.dumps(event_spec["properties"]), "application/json"),
            }

            multipart_data = MultipartEncoder(fields=fields)
            response = requests.post(
                f"{client.base_url}/i/v0/ai",
                data=multipart_data,
                headers={"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {api_key}"},
            )

            assert (
                response.status_code == 200
            ), f"Expected 200 for {event_type}, got {response.status_code}: {response.text}"
            response_data = response.json()
            assert len(response_data["accepted_parts"]) == 2
            logger.info(f"{event_type} event sent successfully")

        logger.info("All event types sent successfully, now querying to verify storage")

        # Query and verify all events
        for event_spec in events_to_test:
            event_type = event_spec["event_type"]
            distinct_id = event_spec["distinct_id"]
            logger.info(f"Querying {event_type} event with distinct_id {distinct_id}")

            event = client.wait_for_event(project_id, event_type, distinct_id)
            assert event is not None, f"Event {event_type} not found"
            assert event["event"] == event_type
            assert event["distinct_id"] == distinct_id
            assert event["properties"]["$ai_model"] == "test-model"
            assert event["properties"]["$ai_provider"] == "test-provider"
            logger.info(f"{event_type} event verified successfully")

        logger.info("All six AI event types verified successfully")

    # ============================================================================
    # PHASE 4: MULTIPART FILE PROCESSING
    # ============================================================================

    # ----------------------------------------------------------------------------
    # Scenario 4.3: Content Type Handling
    # ----------------------------------------------------------------------------

    def test_ai_generation_event_with_different_content_types(self, shared_org_project):
        """Test sending events with blobs using different supported content types."""
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        api_key = shared_org_project["api_key"]

        base_distinct_id = f"user_{uuid.uuid4()}"

        # Send Event 1: application/json blob
        logger.info("Sending event with application/json blob")
        distinct_id_json = f"{base_distinct_id}_json"
        event_data_json = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": distinct_id_json,
            "$set": {"test_user": True, "content_type_test": "json"},
        }
        properties_data_json = {
            "$ai_model": "gpt-4",
            "$ai_model_parameters": {"temperature": 0.7},
        }
        json_blob_data = {"context": "This is JSON formatted LLM input", "tokens": 150}

        fields_json = {
            "event": ("event", json.dumps(event_data_json), "application/json"),
            "event.properties": ("event.properties", json.dumps(properties_data_json), "application/json"),
            "event.properties.$ai_input": ("blob_json", json.dumps(json_blob_data), "application/json"),
        }

        multipart_data_json = MultipartEncoder(fields=fields_json)
        response_json = requests.post(
            f"{client.base_url}/i/v0/ai",
            data=multipart_data_json,
            headers={"Content-Type": multipart_data_json.content_type, "Authorization": f"Bearer {api_key}"},
        )
        assert response_json.status_code == 200, f"Expected 200, got {response_json.status_code}: {response_json.text}"
        response_data_json = response_json.json()
        assert len(response_data_json["accepted_parts"]) == 3
        parts_by_name_json = {part["name"]: part for part in response_data_json["accepted_parts"]}
        assert parts_by_name_json["event.properties.$ai_input"]["content-type"] == "application/json"

        # Send Event 2: text/plain blob
        logger.info("Sending event with text/plain blob")
        distinct_id_text = f"{base_distinct_id}_text"
        event_data_text = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": distinct_id_text,
            "$set": {"test_user": True, "content_type_test": "text"},
        }
        properties_data_text = {
            "$ai_model": "gpt-4",
            "$ai_model_parameters": {"temperature": 0.5},
        }
        text_blob_data = "This is plain text LLM output with multiple lines.\nSecond line here.\nThird line."

        fields_text = {
            "event": ("event", json.dumps(event_data_text), "application/json"),
            "event.properties": ("event.properties", json.dumps(properties_data_text), "application/json"),
            "event.properties.$ai_output": ("blob_text", text_blob_data, "text/plain"),
        }

        multipart_data_text = MultipartEncoder(fields=fields_text)
        response_text = requests.post(
            f"{client.base_url}/i/v0/ai",
            data=multipart_data_text,
            headers={"Content-Type": multipart_data_text.content_type, "Authorization": f"Bearer {api_key}"},
        )
        assert response_text.status_code == 200, f"Expected 200, got {response_text.status_code}: {response_text.text}"
        response_data_text = response_text.json()
        assert len(response_data_text["accepted_parts"]) == 3
        parts_by_name_text = {part["name"]: part for part in response_data_text["accepted_parts"]}
        assert parts_by_name_text["event.properties.$ai_output"]["content-type"] == "text/plain"

        # Send Event 3: application/octet-stream blob
        logger.info("Sending event with application/octet-stream blob")
        distinct_id_binary = f"{base_distinct_id}_binary"
        event_data_binary = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": distinct_id_binary,
            "$set": {"test_user": True, "content_type_test": "binary"},
        }
        properties_data_binary = {
            "$ai_model": "gpt-4",
            "$ai_model_parameters": {"temperature": 0.9},
        }
        binary_blob_data = bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0xFF, 0xFE, 0xFD])

        fields_binary = {
            "event": ("event", json.dumps(event_data_binary), "application/json"),
            "event.properties": ("event.properties", json.dumps(properties_data_binary), "application/json"),
            "event.properties.$ai_embedding_vector": ("blob_binary", binary_blob_data, "application/octet-stream"),
        }

        multipart_data_binary = MultipartEncoder(fields=fields_binary)
        response_binary = requests.post(
            f"{client.base_url}/i/v0/ai",
            data=multipart_data_binary,
            headers={"Content-Type": multipart_data_binary.content_type, "Authorization": f"Bearer {api_key}"},
        )
        assert (
            response_binary.status_code == 200
        ), f"Expected 200, got {response_binary.status_code}: {response_binary.text}"
        response_data_binary = response_binary.json()
        assert len(response_data_binary["accepted_parts"]) == 3
        parts_by_name_binary = {part["name"]: part for part in response_data_binary["accepted_parts"]}
        assert (
            parts_by_name_binary["event.properties.$ai_embedding_vector"]["content-type"] == "application/octet-stream"
        )

        logger.info("All three events sent successfully, now querying to verify storage")

        # Query and verify Event 1 (JSON blob)
        event_json = client.wait_for_event(project_id, "$ai_generation", distinct_id_json)
        assert event_json is not None, "Event with JSON blob not found"
        assert event_json["properties"]["$ai_model"] == "gpt-4"
        logger.info(f"Event 1 (JSON blob) verified: {distinct_id_json}")

        # Query and verify Event 2 (text blob)
        event_text = client.wait_for_event(project_id, "$ai_generation", distinct_id_text)
        assert event_text is not None, "Event with text blob not found"
        assert event_text["properties"]["$ai_model"] == "gpt-4"
        logger.info(f"Event 2 (text blob) verified: {distinct_id_text}")

        # Query and verify Event 3 (binary blob)
        event_binary = client.wait_for_event(project_id, "$ai_generation", distinct_id_binary)
        assert event_binary is not None, "Event with binary blob not found"
        assert event_binary["properties"]["$ai_model"] == "gpt-4"
        logger.info(f"Event 3 (binary blob) verified: {distinct_id_binary}")

        logger.info("All three content type events verified successfully")

        # TODO: Verify blob properties have S3 URLs once S3 upload is implemented

    # ============================================================================
    # PHASE 5: AUTHORIZATION
    # ============================================================================

    # ----------------------------------------------------------------------------
    # Scenario 5.1: API Key Authentication
    # ----------------------------------------------------------------------------

    def test_ai_endpoint_invalid_auth_returns_401(self, function_test_client):
        """Test that requests with invalid API key return 401 Unauthorized."""
        client = function_test_client

        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
        }

        properties_data = {"$ai_model": "test"}

        fields = {
            "event": ("event", json.dumps(event_data), "application/json"),
            "event.properties": ("event.properties", json.dumps(properties_data), "application/json"),
        }

        multipart_data = MultipartEncoder(fields=fields)
        response = requests.post(
            f"{client.base_url}/i/v0/ai",
            data=multipart_data,
            headers={"Content-Type": multipart_data.content_type, "Authorization": "Bearer invalid_key_123"},
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    # ============================================================================
    # PHASE 7: COMPRESSION
    # ============================================================================

    # ----------------------------------------------------------------------------
    # Scenario 7.1: Mixed Compression
    # ----------------------------------------------------------------------------

    def test_ai_generation_event_with_gzip_compression(self, shared_org_project):
        """Test $ai_generation event with gzip compression for the entire request."""
        logger.info("\n" + "=" * 60)
        logger.info("STARTING TEST: $ai_generation Event with Gzip Compression")
        logger.info("=" * 60)

        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        project_api_key = shared_org_project["api_key"]

        logger.info("Step 1: Using shared organization and project")

        logger.info("Step 2: Preparing $ai_generation event")
        distinct_id = f"test_user_{uuid.uuid4().hex[:8]}"
        event_uuid = str(uuid.uuid4())

        event_data = {
            "uuid": event_uuid,
            "event": "$ai_generation",
            "distinct_id": distinct_id,
            "timestamp": "2024-01-15T10:30:00Z",
            "properties": {
                "$ai_model": "gpt-4-compressed",
                "$ai_provider": "openai",
                "$ai_completion_tokens": 75,
                "$ai_prompt_tokens": 30,
                "compression": "gzip",
            },
        }

        input_blob = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Explain compression in simple terms."},
            ],
        }

        output_blob = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Compression reduces data size by encoding information more efficiently.",
                    },
                    "finish_reason": "stop",
                }
            ],
        }

        logger.info("Step 3: Creating multipart request")
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        fields = {
            "event": ("event", json.dumps(event_data), "application/json"),
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

        logger.info("Step 4: Compressing request body with gzip")
        uncompressed_body = multipart_data.to_string()
        compressed_body = gzip.compress(uncompressed_body)

        logger.debug("Uncompressed size: %d bytes", len(uncompressed_body))
        logger.debug("Compressed size: %d bytes", len(compressed_body))
        logger.debug("Compression ratio: %.2f%%", (1 - len(compressed_body) / len(uncompressed_body)) * 100)

        logger.info("Step 5: Sending compressed multipart request to /i/v0/ai endpoint")
        capture_url = f"{client.base_url}/i/v0/ai"
        headers = {
            "Content-Type": multipart_data.content_type,
            "Content-Encoding": "gzip",
            "Authorization": f"Bearer {project_api_key}",
        }

        response = requests.post(capture_url, data=compressed_body, headers=headers)
        response.raise_for_status()
        logger.info("Compressed multipart request sent successfully")

        # Verify response contains accepted parts
        response_data = response.json()
        assert "accepted_parts" in response_data
        accepted_parts = response_data["accepted_parts"]
        assert len(accepted_parts) == 3, f"Expected 3 parts, got {len(accepted_parts)}"

        # Verify each part has correct details (lengths should match uncompressed data)
        event_json = json.dumps(event_data)
        input_json = json.dumps(input_blob)
        output_json = json.dumps(output_blob)

        assert accepted_parts[0]["name"] == "event"
        assert accepted_parts[0]["length"] == len(event_json)
        assert accepted_parts[0]["content-type"] == "application/json"

        assert accepted_parts[1]["name"] == "event.properties.$ai_input"
        assert accepted_parts[1]["length"] == len(input_json)
        assert accepted_parts[1]["content-type"] == "application/json"

        assert accepted_parts[2]["name"] == "event.properties.$ai_output_choices"
        assert accepted_parts[2]["length"] == len(output_json)
        assert accepted_parts[2]["content-type"] == "application/json"

        logger.info("Response validation successful: decompressed parts have correct lengths")

        logger.info("Step 6: Waiting for event to be processed")
        event = client.wait_for_event(
            project_id=project_id, event_name="$ai_generation", distinct_id=distinct_id, timeout=30
        )

        assert event is not None, "$ai_generation event not found after 30 seconds"
        logger.info("Event found in query API")

        logger.info("Step 7: Verifying event properties")
        assert event.get("event") == "$ai_generation"
        assert event.get("distinct_id") == distinct_id

        event_properties = event.get("properties", {})

        assert event_properties.get("$ai_model") == "gpt-4-compressed"
        assert event_properties.get("$ai_provider") == "openai"
        assert event_properties.get("compression") == "gzip"

        assert "$ai_input" in event_properties
        assert "$ai_output_choices" in event_properties

        ai_input_url = event_properties["$ai_input"]
        ai_output_url = event_properties["$ai_output_choices"]

        assert ai_input_url.startswith("s3://")
        assert ai_output_url.startswith("s3://")
        assert "range=" in ai_input_url
        assert "range=" in ai_output_url

        logger.info("All event properties verified successfully")
        logger.info("Gzip compression handled correctly")
        logger.info("Test completed successfully")
        logger.info("=" * 60)
