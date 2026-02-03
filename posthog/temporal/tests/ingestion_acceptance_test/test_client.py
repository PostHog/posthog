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
def client(config: Config, mock_posthog_sdk: MagicMock) -> PostHogClient:
    return PostHogClient(config, mock_posthog_sdk)


class TestCaptureEvent:
    def test_calls_sdk_with_correct_arguments(self, config: Config) -> None:
        mock_sdk = MagicMock()
        client = PostHogClient(config, mock_sdk)
        properties = {"key": "value", "$set": {"email": "test@example.com"}}

        event_uuid = client.capture_event(
            event_name="test_event",
            distinct_id="user_123",
            properties=properties,
        )

        mock_sdk.capture.assert_called_once_with(
            distinct_id="user_123",
            event="test_event",
            properties=properties,
            uuid=event_uuid,
        )

    def test_returns_uuid(self, config: Config) -> None:
        mock_sdk = MagicMock()
        client = PostHogClient(config, mock_sdk)

        event_uuid = client.capture_event(event_name="test_event", distinct_id="user_123")

        assert event_uuid is not None
        assert len(event_uuid) == 36  # UUID format

    def test_uses_empty_dict_when_no_properties(self, config: Config) -> None:
        mock_sdk = MagicMock()
        client = PostHogClient(config, mock_sdk)

        client.capture_event(event_name="test_event", distinct_id="user_123")

        call_kwargs = mock_sdk.capture.call_args[1]
        assert call_kwargs["properties"] == {}


class TestFetchEventByUuid:
    @patch("posthog.temporal.ingestion_acceptance_test.client.requests.post")
    def test_sends_correct_hogql_query(self, mock_post: MagicMock, client: PostHogClient) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"results": [], "columns": []}

        client._fetch_event_by_uuid("test-uuid-123")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]

        assert call_kwargs["headers"] == {"Authorization": "Bearer phx_personal_key"}
        assert call_kwargs["timeout"] == 10

        request_body = call_kwargs["json"]
        assert request_body["query"]["kind"] == "HogQLQuery"
        assert "WHERE uuid = {event_uuid}" in request_body["query"]["query"]
        assert request_body["query"]["values"] == {"event_uuid": "test-uuid-123"}
        assert request_body["refresh"] == "force_blocking"

    @patch("posthog.temporal.ingestion_acceptance_test.client.requests.post")
    def test_posts_to_correct_url(self, mock_post: MagicMock, client: PostHogClient) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"results": [], "columns": []}

        client._fetch_event_by_uuid("test-uuid")

        url = mock_post.call_args[0][0]
        assert url == "https://test.posthog.com/api/environments/12345/query/"

    @patch("posthog.temporal.ingestion_acceptance_test.client.requests.post")
    def test_returns_captured_event_when_found(self, mock_post: MagicMock, client: PostHogClient) -> None:
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

    @patch("posthog.temporal.ingestion_acceptance_test.client.requests.post")
    def test_returns_none_when_not_found(self, mock_post: MagicMock, client: PostHogClient) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"results": [], "columns": []}

        result = client._fetch_event_by_uuid("nonexistent-uuid")

        assert result is None


class TestFetchPersonByDistinctId:
    @patch("posthog.temporal.ingestion_acceptance_test.client.requests.post")
    def test_sends_correct_hogql_query_with_join(self, mock_post: MagicMock, client: PostHogClient) -> None:
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

    @patch("posthog.temporal.ingestion_acceptance_test.client.requests.post")
    def test_returns_person_when_found(self, mock_post: MagicMock, client: PostHogClient) -> None:
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

    @patch("posthog.temporal.ingestion_acceptance_test.client.requests.post")
    def test_returns_none_when_not_found(self, mock_post: MagicMock, client: PostHogClient) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"results": [], "columns": []}

        result = client._fetch_person_by_distinct_id("nonexistent-user")

        assert result is None
