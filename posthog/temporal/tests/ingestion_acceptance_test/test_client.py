import json
import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ingestion_acceptance_test.client import CapturedEvent, Person, PostHogClient
from posthog.temporal.ingestion_acceptance_test.config import Config


@pytest.fixture
def config() -> Config:
    return Config(
        api_host="https://test.posthog.com",
        project_api_key="phc_test_key",
        project_id="12345",
        personal_api_key="phx_personal_key",
        event_timeout_seconds=5,
        poll_interval_seconds=0.1,
    )


@pytest.fixture
def mock_posthog_sdk() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(config: Config, mock_posthog_sdk: MagicMock) -> Generator[PostHogClient, None, None]:
    client = PostHogClient(config, mock_posthog_sdk)
    yield client
    client.shutdown()


class TestCaptureEvent:
    def test_calls_sdk_with_correct_arguments(self, client: PostHogClient, mock_posthog_sdk: MagicMock) -> None:
        properties = {"key": "value", "$set": {"email": "test@example.com"}}

        event_uuid = client.capture_event(
            event_name="test_event",
            distinct_id="user_123",
            properties=properties,
        )

        mock_posthog_sdk.capture.assert_called_once_with(
            distinct_id="user_123",
            event="test_event",
            properties=properties,
            uuid=event_uuid,
        )

    def test_uses_empty_dict_when_no_properties(self, client: PostHogClient, mock_posthog_sdk: MagicMock) -> None:
        client.capture_event(event_name="test_event", distinct_id="user_123")

        call_kwargs = mock_posthog_sdk.capture.call_args[1]
        assert call_kwargs["properties"] == {}


class TestFetchEventByUuid:
    def test_sends_correct_hogql_query(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": [], "columns": []}

            client._fetch_event_by_uuid("test-uuid-123")

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]

            assert call_kwargs["headers"] == {"Authorization": "Bearer phx_personal_key"}
            assert call_kwargs["timeout"] == PostHogClient.HTTP_TIMEOUT_SECONDS

            request_body = call_kwargs["json"]
            assert request_body["query"]["kind"] == "HogQLQuery"
            assert "WHERE uuid = {event_uuid}" in request_body["query"]["query"]
            assert "timestamp >= {min_timestamp}" in request_body["query"]["query"]
            assert request_body["query"]["values"]["event_uuid"] == "test-uuid-123"
            assert "min_timestamp" in request_body["query"]["values"]
            assert request_body["refresh"] == "force_blocking"

    def test_posts_to_correct_url(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": [], "columns": []}

            client._fetch_event_by_uuid("test-uuid")

            url = mock_post.call_args[0][0]
            assert url == "https://test.posthog.com/api/projects/12345/query/"

    def test_returns_captured_event_when_found(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "results": [["uuid-123", "test_event", "user_456", '{"key": "value"}', "2024-01-01T00:00:00Z"]],
                "columns": ["uuid", "event", "distinct_id", "properties", "timestamp"],
            }

            result = client._fetch_event_by_uuid("uuid-123")

            assert result is not None
            assert isinstance(result, CapturedEvent)
            assert result.uuid == "uuid-123"
            assert result.event == "test_event"
            assert result.distinct_id == "user_456"
            assert result.properties == {"key": "value"}
            assert result.timestamp == "2024-01-01T00:00:00Z"

    def test_returns_none_when_not_found(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": [], "columns": []}

            result = client._fetch_event_by_uuid("nonexistent-uuid")

            assert result is None


class TestFetchPersonByDistinctId:
    def test_sends_correct_hogql_query_with_join(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": [], "columns": []}

            client._fetch_person_by_distinct_id("user_123")

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]

            request_body = call_kwargs["json"]
            query = request_body["query"]["query"]

            assert "FROM persons p" in query
            assert "JOIN person_distinct_ids pdi ON p.id = pdi.person_id" in query
            assert "WHERE pdi.distinct_id = {distinct_id}" in query
            assert request_body["query"]["values"] == {"distinct_id": "user_123"}

    def test_returns_person_when_found(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "results": [["person-id-123", '{"email": "test@example.com", "name": "Test"}', "2024-01-01T00:00:00Z"]],
                "columns": ["id", "properties", "created_at"],
            }

            result = client._fetch_person_by_distinct_id("user_123")

            assert result is not None
            assert isinstance(result, Person)
            assert result.id == "person-id-123"
            assert result.properties == {"email": "test@example.com", "name": "Test"}
            assert result.created_at == "2024-01-01T00:00:00Z"

    def test_returns_none_when_not_found(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": [], "columns": []}

            result = client._fetch_person_by_distinct_id("nonexistent-user")

            assert result is None


class MockHttpHandler(BaseHTTPRequestHandler):
    """HTTP handler that returns configurable responses for testing retry behavior."""

    # Use HTTP/1.0 to avoid keep-alive connection issues in tests
    protocol_version = "HTTP/1.0"

    queued_responses: list[dict[str, Any]] = []
    call_count: int = 0

    def do_POST(self) -> None:
        MockHttpHandler.call_count += 1

        if MockHttpHandler.queued_responses:
            resp = MockHttpHandler.queued_responses.pop(0)
            status_code = resp.get("status_code", 200)
            body = resp.get("json", {"results": [], "columns": []})
        else:
            status_code = 200
            body = {"results": [], "columns": []}

        body_bytes = json.dumps(body).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress logging


@pytest.fixture
def mock_server() -> Generator[HTTPServer, None, None]:
    """Create a test HTTP server on a random available port."""
    MockHttpHandler.queued_responses = []
    MockHttpHandler.call_count = 0

    server = HTTPServer(("127.0.0.1", 0), MockHttpHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    yield server

    server.shutdown()


class TestHttpRetryBehavior:
    """Test HTTP retry behavior using a real test server."""

    def test_retries_on_500_error_then_succeeds(self, mock_server: HTTPServer, mock_posthog_sdk: MagicMock) -> None:
        port = mock_server.server_address[1]
        config = Config(
            api_host=f"http://127.0.0.1:{port}",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            event_timeout_seconds=5,
            poll_interval_seconds=0.1,
        )

        MockHttpHandler.queued_responses = [
            {"status_code": 500},
            {"status_code": 500},
            {"json": {"results": [], "columns": []}, "status_code": 200},
        ]

        client = PostHogClient(config, mock_posthog_sdk)
        result = client._execute_hogql_query_all("SELECT 1", {})
        client.shutdown()

        assert result == []
        assert MockHttpHandler.call_count == 3

    def test_retries_on_502_503_504_errors(self, mock_server: HTTPServer, mock_posthog_sdk: MagicMock) -> None:
        port = mock_server.server_address[1]
        config = Config(
            api_host=f"http://127.0.0.1:{port}",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            event_timeout_seconds=5,
            poll_interval_seconds=0.1,
        )

        MockHttpHandler.queued_responses = [
            {"status_code": 502},
            {"status_code": 503},
            {"status_code": 504},
            {"json": {"results": [], "columns": []}, "status_code": 200},
        ]

        client = PostHogClient(config, mock_posthog_sdk)
        result = client._execute_hogql_query_all("SELECT 1", {})
        client.shutdown()

        assert result == []
        assert MockHttpHandler.call_count == 4

    def test_does_not_retry_on_400_error(self, mock_server: HTTPServer, mock_posthog_sdk: MagicMock) -> None:
        port = mock_server.server_address[1]
        config = Config(
            api_host=f"http://127.0.0.1:{port}",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            event_timeout_seconds=5,
            poll_interval_seconds=0.1,
        )

        MockHttpHandler.queued_responses = [{"status_code": 400, "json": {"error": "Bad request"}}]

        client = PostHogClient(config, mock_posthog_sdk)
        with pytest.raises(Exception):
            client._execute_hogql_query_all("SELECT 1", {})
        client.shutdown()

        assert MockHttpHandler.call_count == 1

    def test_does_not_retry_on_429_rate_limit(self, mock_server: HTTPServer, mock_posthog_sdk: MagicMock) -> None:
        port = mock_server.server_address[1]
        config = Config(
            api_host=f"http://127.0.0.1:{port}",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            event_timeout_seconds=5,
            poll_interval_seconds=0.1,
        )

        MockHttpHandler.queued_responses = [{"status_code": 429, "json": {"error": "Rate limited"}}]

        client = PostHogClient(config, mock_posthog_sdk)
        with pytest.raises(Exception):
            client._execute_hogql_query_all("SELECT 1", {})
        client.shutdown()

        assert MockHttpHandler.call_count == 1

    def test_returns_empty_list_on_404(self, mock_server: HTTPServer, mock_posthog_sdk: MagicMock) -> None:
        port = mock_server.server_address[1]
        config = Config(
            api_host=f"http://127.0.0.1:{port}",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            event_timeout_seconds=5,
            poll_interval_seconds=0.1,
        )

        MockHttpHandler.queued_responses = [{"status_code": 404}]

        client = PostHogClient(config, mock_posthog_sdk)
        result = client._execute_hogql_query_all("SELECT 1", {})
        client.shutdown()

        assert result == []
        assert MockHttpHandler.call_count == 1

    def test_succeeds_on_first_try_when_server_healthy(
        self, mock_server: HTTPServer, mock_posthog_sdk: MagicMock
    ) -> None:
        port = mock_server.server_address[1]
        config = Config(
            api_host=f"http://127.0.0.1:{port}",
            project_api_key="phc_test_key",
            project_id="12345",
            personal_api_key="phx_personal_key",
            event_timeout_seconds=5,
            poll_interval_seconds=0.1,
        )

        MockHttpHandler.queued_responses = [{"json": {"results": [["value"]], "columns": ["col"]}, "status_code": 200}]

        client = PostHogClient(config, mock_posthog_sdk)
        result = client._execute_hogql_query_all("SELECT 1", {})
        client.shutdown()

        assert result == [{"col": "value"}]
        assert MockHttpHandler.call_count == 1


class TestTimestampFiltering:
    def test_client_stores_test_start_date(self, client: PostHogClient) -> None:
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)

        assert client._test_start_date == yesterday

    def test_fetch_events_by_person_id_includes_timestamp_filter(self, client: PostHogClient) -> None:
        with patch.object(client._session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": [], "columns": []}

            client._fetch_events_by_person_id("test-person-id", expected_count=1)

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            request_body = call_kwargs["json"]

            assert "timestamp >= {min_timestamp}" in request_body["query"]["query"]
            assert "min_timestamp" in request_body["query"]["values"]
            assert request_body["query"]["values"]["min_timestamp"] == client._test_start_date.isoformat()
