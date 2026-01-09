"""LLM Analytics capture tests - tests multipart blob upload and S3 storage."""

import os
import re
import gzip
import json
import uuid
import logging

import pytest

import boto3
import requests
from botocore.config import Config as BotoConfig
from multipart import multipart
from requests_toolbelt import MultipartEncoder

logger = logging.getLogger(__name__)


def parse_s3_url(s3_url: str) -> tuple[str, str, int, int]:
    """Parse an S3 URL with range parameter.

    Args:
        s3_url: URL in format s3://bucket/key?range=start-end

    Returns:
        Tuple of (bucket, key, range_start, range_end)
    """
    # Parse s3://bucket/key?range=start-end
    match = re.match(r"s3://([^/]+)/(.+)\?range=(\d+)-(\d+)", s3_url)
    if not match:
        raise ValueError(f"Invalid S3 URL format: {s3_url}")

    bucket = match.group(1)
    key = match.group(2)
    range_start = int(match.group(3))
    range_end = int(match.group(4))

    return bucket, key, range_start, range_end


def get_s3_client():
    """Create an S3 client using environment variables.

    Required environment variables:
        AI_S3_ENDPOINT: S3 endpoint URL (e.g., http://localhost:19000)
        AI_S3_ACCESS_KEY_ID: S3 access key
        AI_S3_SECRET_ACCESS_KEY: S3 secret key
        AI_S3_REGION: S3 region (optional, defaults to us-east-1)

    Raises:
        ValueError: If required environment variables are not set.
    """
    endpoint_url = os.environ.get("AI_S3_ENDPOINT")
    access_key = os.environ.get("AI_S3_ACCESS_KEY_ID")
    secret_key = os.environ.get("AI_S3_SECRET_ACCESS_KEY")
    region = os.environ.get("AI_S3_REGION", "us-east-1")

    missing = []
    if not endpoint_url:
        missing.append("AI_S3_ENDPOINT")
    if not access_key:
        missing.append("AI_S3_ACCESS_KEY_ID")
    if not secret_key:
        missing.append("AI_S3_SECRET_ACCESS_KEY")

    if missing:
        raise ValueError(f"Missing required S3 environment variables: {', '.join(missing)}")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=BotoConfig(signature_version="s3v4"),
    )


def fetch_blob_from_s3(s3_url: str) -> bytes:
    """Fetch blob data from S3 using the URL with range parameter.

    Args:
        s3_url: URL in format s3://bucket/key?range=start-end

    Returns:
        The blob data as bytes

    Raises:
        ValueError: If S3 credentials are not configured.
    """
    bucket, key, range_start, range_end = parse_s3_url(s3_url)

    s3_client = get_s3_client()

    # Fetch the object with byte range
    response = s3_client.get_object(Bucket=bucket, Key=key, Range=f"bytes={range_start}-{range_end}")

    return response["Body"].read()


def fetch_full_s3_object(s3_url: str) -> tuple[bytes, str]:
    """Fetch the full S3 object (not just a range).

    Args:
        s3_url: URL in format s3://bucket/key?range=start-end

    Returns:
        Tuple of (object bytes, content-type header)
    """
    bucket, key, _, _ = parse_s3_url(s3_url)
    s3_client = get_s3_client()
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read(), response.get("ContentType", "")


def parse_multipart_data(data: bytes, boundary: str) -> list[dict]:
    """Parse multipart data and return list of parts with headers and body.

    Args:
        data: Raw multipart bytes
        boundary: The boundary string (without -- prefix)

    Returns:
        List of dicts with keys: name, content_type, content_encoding, body
    """
    parts: list[dict] = []

    # python-multipart uses callbacks
    current_part: dict = {}

    def on_part_begin() -> None:
        nonlocal current_part
        current_part = {"headers": {}, "body": b""}

    def on_part_data(data: bytes, start: int, end: int) -> None:
        current_part["body"] += data[start:end]

    def on_part_end() -> None:
        # Extract name from Content-Disposition
        content_disposition = current_part["headers"].get("Content-Disposition", "")
        name_match = re.search(r'name="([^"]+)"', content_disposition)
        name = name_match.group(1) if name_match else ""

        parts.append(
            {
                "name": name,
                "content_type": current_part["headers"].get("Content-Type", "application/octet-stream"),
                "content_encoding": current_part["headers"].get("Content-Encoding"),
                "body": current_part["body"],
            }
        )

    def on_header_field(data: bytes, start: int, end: int) -> None:
        current_part["_header_field"] = data[start:end].decode("utf-8")

    def on_header_value(data: bytes, start: int, end: int) -> None:
        field = current_part.get("_header_field", "")
        current_part["headers"][field] = data[start:end].decode("utf-8")

    callbacks = {
        "on_part_begin": on_part_begin,
        "on_part_data": on_part_data,
        "on_part_end": on_part_end,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
    }

    parser = multipart.MultipartParser(boundary.encode("utf-8"), callbacks)
    parser.write(data)
    parser.finalize()

    return parts


def parse_mime_part(data: bytes) -> tuple[dict[str, str], bytes]:
    """Parse a MIME part (headers + body) using the standard email parser.

    The byte range format is a standard MIME part:
        Content-Disposition: form-data; name="property_name"\r\n
        Content-Type: application/json\r\n
        [Content-Encoding: gzip\r\n]
        \r\n
        <body bytes>

    Args:
        data: Raw bytes containing headers and body separated by \r\n\r\n

    Returns:
        Tuple of (headers dict with lowercase keys, body bytes)
    """
    from email import policy
    from email.parser import BytesParser

    # Parse as a MIME message
    parser = BytesParser(policy=policy.HTTP)
    msg = parser.parsebytes(data)

    # Extract headers (lowercase keys for consistency)
    headers: dict[str, str] = {k.lower(): str(v) for k, v in msg.items()}

    # Get raw body bytes
    payload = msg.get_payload(decode=True)
    body: bytes
    if payload is None:
        raw_payload = msg.get_payload()
        if isinstance(raw_payload, str):
            body = raw_payload.encode("utf-8")
        else:
            body = b""
    elif isinstance(payload, bytes):
        body = payload
    else:
        body = b""

    return headers, body


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
                "$ai_output_tokens": 150,
                "$ai_input_tokens": 50,
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
        assert event_properties.get("$ai_output_tokens") == 150
        assert event_properties.get("$ai_input_tokens") == 50
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
            "$ai_output_tokens": 100,
            "$ai_input_tokens": 25,
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
        assert event_properties.get("$ai_output_tokens") == 100
        assert event_properties.get("$ai_input_tokens") == 25
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

        # Verify blob properties have S3 URLs
        # Event 1: $ai_input should be an S3 URL
        ai_input_url = event_json["properties"].get("$ai_input")
        assert ai_input_url is not None, "Event 1 should have $ai_input property"
        assert ai_input_url.startswith("s3://"), f"$ai_input should be an S3 URL, got: {ai_input_url}"
        assert "?range=" in ai_input_url, f"$ai_input URL should have range parameter, got: {ai_input_url}"
        logger.info(f"Event 1 $ai_input S3 URL verified: {ai_input_url}")

        # Event 2: $ai_output should be an S3 URL
        ai_output_url = event_text["properties"].get("$ai_output")
        assert ai_output_url is not None, "Event 2 should have $ai_output property"
        assert ai_output_url.startswith("s3://"), f"$ai_output should be an S3 URL, got: {ai_output_url}"
        assert "?range=" in ai_output_url, f"$ai_output URL should have range parameter, got: {ai_output_url}"
        logger.info(f"Event 2 $ai_output S3 URL verified: {ai_output_url}")

        # Event 3: $ai_embedding_vector should be an S3 URL
        ai_embedding_url = event_binary["properties"].get("$ai_embedding_vector")
        assert ai_embedding_url is not None, "Event 3 should have $ai_embedding_vector property"
        assert ai_embedding_url.startswith(
            "s3://"
        ), f"$ai_embedding_vector should be an S3 URL, got: {ai_embedding_url}"
        assert (
            "?range=" in ai_embedding_url
        ), f"$ai_embedding_vector URL should have range parameter, got: {ai_embedding_url}"
        logger.info(f"Event 3 $ai_embedding_vector S3 URL verified: {ai_embedding_url}")

    def test_ai_blob_data_stored_correctly_in_s3(self, shared_org_project):
        """Test that blob data is correctly stored in S3 as multipart/mixed format.

        Verifies:
        1. Each property's byte range can be fetched and parsed as a standalone multipart document
        2. The full S3 object can be parsed as a multipart document containing all parts
        3. Headers (Content-Type, Content-Disposition) are preserved correctly
        4. Body content matches the original data
        """
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        api_key = shared_org_project["api_key"]

        logger.info("Sending event with multiple blobs to verify S3 multipart storage")

        distinct_id = f"s3_storage_test_{uuid.uuid4().hex[:8]}"
        event_uuid = str(uuid.uuid4())

        # Create distinct blob data that we can verify
        json_blob_data = {"test_key": "test_value", "number": 42, "nested": {"a": 1}}
        text_blob_data = "This is test text blob data for S3 verification.\nLine 2."
        binary_blob_data = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01, 0x02, 0x03])

        event_data = {
            "uuid": event_uuid,
            "event": "$ai_generation",
            "distinct_id": distinct_id,
        }

        properties_data = {
            "$ai_model": "test-s3-storage",
        }

        fields = {
            "event": ("event", json.dumps(event_data), "application/json"),
            "event.properties": ("event.properties", json.dumps(properties_data), "application/json"),
            "event.properties.$ai_input": ("json_blob", json.dumps(json_blob_data), "application/json"),
            "event.properties.$ai_output": ("text_blob", text_blob_data, "text/plain"),
            "event.properties.$ai_embedding_vector": ("binary_blob", binary_blob_data, "application/octet-stream"),
        }

        multipart_data = MultipartEncoder(fields=fields)
        response = requests.post(
            f"{client.base_url}/i/v0/ai",
            data=multipart_data,
            headers={"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {api_key}"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        # Wait for event to be stored
        event = client.wait_for_event(project_id, "$ai_generation", distinct_id)
        assert event is not None, "Event not found"

        # Get and verify the S3 URLs from properties
        ai_input_url = event["properties"].get("$ai_input")
        ai_output_url = event["properties"].get("$ai_output")
        ai_embedding_url = event["properties"].get("$ai_embedding_vector")

        # Verify URLs exist and have correct format
        assert ai_input_url is not None, "$ai_input property not found"
        assert ai_output_url is not None, "$ai_output property not found"
        assert ai_embedding_url is not None, "$ai_embedding_vector property not found"

        assert ai_input_url.startswith("s3://"), f"$ai_input should be S3 URL, got: {ai_input_url}"
        assert ai_output_url.startswith("s3://"), f"$ai_output should be S3 URL, got: {ai_output_url}"
        assert ai_embedding_url.startswith("s3://"), f"$ai_embedding_vector should be S3 URL, got: {ai_embedding_url}"

        assert "?range=" in ai_input_url, f"$ai_input should have range param, got: {ai_input_url}"
        assert "?range=" in ai_output_url, f"$ai_output should have range param, got: {ai_output_url}"
        assert "?range=" in ai_embedding_url, f"$ai_embedding_vector should have range param, got: {ai_embedding_url}"

        logger.info("S3 URLs verified:")
        logger.info(f"  $ai_input: {ai_input_url}")
        logger.info(f"  $ai_output: {ai_output_url}")
        logger.info(f"  $ai_embedding_vector: {ai_embedding_url}")

        # Verify all blobs are stored in the same S3 object (same base URL, different ranges)
        base_url_input = ai_input_url.split("?")[0]
        base_url_output = ai_output_url.split("?")[0]
        base_url_embedding = ai_embedding_url.split("?")[0]

        assert base_url_input == base_url_output == base_url_embedding, (
            f"All blobs should be in same S3 object. Got:\n"
            f"  input: {base_url_input}\n"
            f"  output: {base_url_output}\n"
            f"  embedding: {base_url_embedding}"
        )
        logger.info(f"All blobs stored in same S3 object: {base_url_input}")

        # Verify ranges are sequential and non-overlapping
        # Note: ranges exclude boundaries, so first part doesn't start at 0
        _, _, input_start, input_end = parse_s3_url(ai_input_url)
        _, _, output_start, output_end = parse_s3_url(ai_output_url)
        _, _, embedding_start, embedding_end = parse_s3_url(ai_embedding_url)

        assert output_start > input_end, f"Second blob should start after first ends"
        assert embedding_start > output_end, f"Third blob should start after second ends"

        logger.info(
            f"Byte ranges verified: {input_start}-{input_end}, {output_start}-{output_end}, {embedding_start}-{embedding_end}"
        )

        # =========================================================================
        # TEST 1: Verify S3 object metadata and full document parses as multipart
        # =========================================================================
        logger.info("TEST 1: Verifying S3 object metadata and full document...")

        full_data, content_type = fetch_full_s3_object(ai_input_url)
        logger.info(f"Full S3 object size: {len(full_data)} bytes")
        logger.info(f"Content-Type header: {content_type}")

        # Extract boundary from Content-Type header (format: multipart/mixed; boundary=...)
        assert "multipart/mixed" in content_type, f"Expected multipart/mixed content type, got: {content_type}"
        boundary_match = re.search(r"boundary=([^\s;]+)", content_type)
        assert boundary_match, f"Could not extract boundary from Content-Type: {content_type}"
        boundary = boundary_match.group(1)
        logger.info(f"Boundary: {boundary}")

        # Parse the full document as multipart to verify it's valid
        all_parts = parse_multipart_data(full_data, boundary)
        assert len(all_parts) == 3, f"Expected 3 parts in full document, got {len(all_parts)}"

        # Verify all parts are present with correct content
        assert all_parts[0]["name"] == "$ai_input"
        assert all_parts[0]["content_type"] == "application/json"
        assert json.loads(all_parts[0]["body"].decode("utf-8")) == json_blob_data

        assert all_parts[1]["name"] == "$ai_output"
        assert all_parts[1]["content_type"] == "text/plain"
        assert all_parts[1]["body"].decode("utf-8") == text_blob_data

        assert all_parts[2]["name"] == "$ai_embedding_vector"
        assert all_parts[2]["content_type"] == "application/octet-stream"
        assert all_parts[2]["body"] == binary_blob_data

        logger.info("TEST 1 PASSED: Full document parses as valid multipart with all 3 parts")

        # =========================================================================
        # TEST 2: Fetch each range separately and parse as MIME part
        # Each range contains headers + body (no boundaries), which can be parsed
        # using the standard email/MIME parser.
        # =========================================================================
        logger.info("TEST 2: Fetching each range separately and parsing as MIME part...")

        # Test range fetch for $ai_input
        input_range_data = fetch_blob_from_s3(ai_input_url)
        input_headers, input_body = parse_mime_part(input_range_data)
        assert "$ai_input" in input_headers.get("content-disposition", "")
        assert input_headers.get("content-type") == "application/json"
        assert json.loads(input_body.decode("utf-8")) == json_blob_data
        logger.info("$ai_input range fetch and parse: PASSED")

        # Test range fetch for $ai_output
        output_range_data = fetch_blob_from_s3(ai_output_url)
        output_headers, output_body = parse_mime_part(output_range_data)
        assert "$ai_output" in output_headers.get("content-disposition", "")
        assert output_headers.get("content-type") == "text/plain"
        assert output_body.decode("utf-8") == text_blob_data
        logger.info("$ai_output range fetch and parse: PASSED")

        # Test range fetch for $ai_embedding_vector
        embedding_range_data = fetch_blob_from_s3(ai_embedding_url)
        embedding_headers, embedding_body = parse_mime_part(embedding_range_data)
        assert "$ai_embedding_vector" in embedding_headers.get("content-disposition", "")
        assert embedding_headers.get("content-type") == "application/octet-stream"
        assert embedding_body == binary_blob_data
        logger.info("$ai_embedding_vector range fetch and parse: PASSED")

        logger.info("TEST 2 PASSED: Each range can be fetched and parsed as MIME part")
        logger.info("S3 multipart blob storage verification complete")

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
                "$ai_output_tokens": 75,
                "$ai_input_tokens": 30,
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
