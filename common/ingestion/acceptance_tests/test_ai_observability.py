"""AI observability capture tests - tests the multipart event transport on /i/v0/ai."""

import gzip
import json
import uuid
import logging

import pytest

import requests
from requests_toolbelt import MultipartEncoder

logger = logging.getLogger(__name__)


def post_multipart(base_url: str, api_key: str, fields: dict) -> requests.Response:
    multipart_data = MultipartEncoder(fields=fields)
    return requests.post(
        f"{base_url}/i/v0/ai",
        data=multipart_data,
        headers={"Content-Type": multipart_data.content_type, "Authorization": f"Bearer {api_key}"},
    )


@pytest.mark.usefixtures("shared_org_project")
class TestAIObservability:
    def test_basic_ai_generation_event(self, shared_org_project):
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        project_api_key = shared_org_project["api_key"]

        distinct_id = f"test_user_{uuid.uuid4().hex[:8]}"
        ai_input = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France?"},
        ]

        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": distinct_id,
            "timestamp": "2024-01-15T10:30:00Z",
            "properties": {
                "$ai_model": "gpt-4",
                "$ai_provider": "openai",
                "$ai_output_tokens": 150,
                "$ai_input_tokens": 50,
                "$ai_input": ai_input,
                "custom_property": "test_value",
            },
        }

        response = post_multipart(
            client.base_url,
            project_api_key,
            {"event": ("event", json.dumps(event_data), "application/json")},
        )
        response.raise_for_status()

        response_data = response.json()
        accepted_parts = response_data["accepted_parts"]
        assert len(accepted_parts) == 1, f"Expected 1 part, got {len(accepted_parts)}"
        assert accepted_parts[0]["name"] == "event"
        assert accepted_parts[0]["length"] == len(json.dumps(event_data))
        assert accepted_parts[0]["content-type"] == "application/json"

        event = client.wait_for_event(
            project_id=project_id, event_name="$ai_generation", distinct_id=distinct_id, timeout=30
        )
        assert event is not None, "$ai_generation event not found after 30 seconds"
        assert event.get("event") == "$ai_generation"
        assert event.get("distinct_id") == distinct_id

        event_properties = event.get("properties", {})
        assert event_properties.get("$ai_model") == "gpt-4"
        assert event_properties.get("$ai_provider") == "openai"
        assert event_properties.get("$ai_output_tokens") == 150
        assert event_properties.get("$ai_input_tokens") == 50
        assert event_properties.get("custom_property") == "test_value"
        assert event_properties.get("$ai_input") == ai_input

    def test_ai_generation_event_with_separate_properties(self, shared_org_project):
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        project_api_key = shared_org_project["api_key"]

        distinct_id = f"test_user_{uuid.uuid4().hex[:8]}"
        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": distinct_id,
        }
        properties_data = {
            "$ai_model": "gpt-4",
            "$ai_provider": "openai",
            "$ai_input": [{"role": "user", "content": "Hello"}],
        }

        response = post_multipart(
            client.base_url,
            project_api_key,
            {
                "event": ("event", json.dumps(event_data), "application/json"),
                "event.properties": ("event.properties", json.dumps(properties_data), "application/json"),
            },
        )
        response.raise_for_status()

        accepted_parts = response.json()["accepted_parts"]
        assert len(accepted_parts) == 2, f"Expected 2 parts, got {len(accepted_parts)}"
        assert accepted_parts[0]["name"] == "event"
        assert accepted_parts[1]["name"] == "event.properties"
        assert accepted_parts[1]["length"] == len(json.dumps(properties_data))

        event = client.wait_for_event(
            project_id=project_id, event_name="$ai_generation", distinct_id=distinct_id, timeout=30
        )
        assert event is not None, "$ai_generation event not found after 30 seconds"
        event_properties = event.get("properties", {})
        assert event_properties.get("$ai_model") == "gpt-4"
        assert event_properties.get("$ai_input") == [{"role": "user", "content": "Hello"}]

    def test_blob_parts_are_rejected(self, shared_org_project):
        client = shared_org_project["client"]
        project_api_key = shared_org_project["api_key"]

        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": f"test_user_{uuid.uuid4().hex[:8]}",
            "properties": {"$ai_model": "gpt-4"},
        }

        response = post_multipart(
            client.base_url,
            project_api_key,
            {
                "event": ("event", json.dumps(event_data), "application/json"),
                "event.properties.$ai_input": (
                    f"blob_{uuid.uuid4().hex[:8]}",
                    json.dumps({"messages": []}),
                    "application/json",
                ),
            },
        )

        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        assert "Unknown multipart field" in response.text

    def test_all_accepted_ai_event_types(self, shared_org_project):
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        api_key = shared_org_project["api_key"]

        base_distinct_id = f"user_{uuid.uuid4()}"

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

            response = post_multipart(
                client.base_url,
                api_key,
                {
                    "event": ("event", json.dumps(event_data), "application/json"),
                    "event.properties": ("event.properties", json.dumps(event_spec["properties"]), "application/json"),
                },
            )

            assert response.status_code == 200, (
                f"Expected 200 for {event_type}, got {response.status_code}: {response.text}"
            )
            assert len(response.json()["accepted_parts"]) == 2
            logger.info(f"{event_type} event sent successfully")

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

    def test_ai_endpoint_invalid_auth_returns_401(self, function_test_client):
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

    def test_ai_generation_event_with_gzip_compression(self, shared_org_project):
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]
        project_api_key = shared_org_project["api_key"]

        distinct_id = f"test_user_{uuid.uuid4().hex[:8]}"
        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "distinct_id": distinct_id,
            "timestamp": "2024-01-15T10:30:00Z",
        }
        properties_data = {
            "$ai_model": "gpt-4-compressed",
            "$ai_provider": "openai",
            "$ai_output_tokens": 75,
            "$ai_input_tokens": 30,
            "compression": "gzip",
        }

        fields = {
            "event": ("event", json.dumps(event_data), "application/json"),
            "event.properties": ("event.properties", json.dumps(properties_data), "application/json"),
        }
        multipart_data = MultipartEncoder(fields=fields)
        compressed_body = gzip.compress(multipart_data.to_string())

        response = requests.post(
            f"{client.base_url}/i/v0/ai",
            data=compressed_body,
            headers={
                "Content-Type": multipart_data.content_type,
                "Content-Encoding": "gzip",
                "Authorization": f"Bearer {project_api_key}",
            },
        )
        response.raise_for_status()

        accepted_parts = response.json()["accepted_parts"]
        assert len(accepted_parts) == 2, f"Expected 2 parts, got {len(accepted_parts)}"
        assert accepted_parts[0]["name"] == "event"
        assert accepted_parts[0]["length"] == len(json.dumps(event_data))
        assert accepted_parts[1]["name"] == "event.properties"
        assert accepted_parts[1]["length"] == len(json.dumps(properties_data))

        event = client.wait_for_event(
            project_id=project_id, event_name="$ai_generation", distinct_id=distinct_id, timeout=30
        )
        assert event is not None, "$ai_generation event not found after 30 seconds"
        event_properties = event.get("properties", {})
        assert event_properties.get("$ai_model") == "gpt-4-compressed"
        assert event_properties.get("compression") == "gzip"
