import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ingestion_acceptance_test.client import CapturedEvent, Person, PostHogClient
from posthog.temporal.ingestion_acceptance_test.config import Config


@pytest.fixture
def config() -> Config:
    return Config(
        api_host="https://test.posthog.com",
        project_api_key="phc_test_key",
        team_id=12345,
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
            properties={"$ignore_sent_at": True, **properties},
            uuid=event_uuid,
        )

    def test_uses_empty_dict_when_no_properties(self, client: PostHogClient, mock_posthog_sdk: MagicMock) -> None:
        client.capture_event(event_name="test_event", distinct_id="user_123")

        call_kwargs = mock_posthog_sdk.capture.call_args[1]
        assert call_kwargs["properties"] == {"$ignore_sent_at": True}


class TestFetchEventByUuid:
    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_sends_correct_clickhouse_query(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = []

        client._fetch_event_by_uuid("test-uuid-123")

        mock_sync_execute.assert_called_once()
        query = mock_sync_execute.call_args[0][0]
        params = mock_sync_execute.call_args[0][1]

        assert "WHERE team_id = %(team_id)s" in query
        assert "uuid = %(event_uuid)s" in query
        assert "timestamp >= %(min_timestamp)s" in query
        assert params["team_id"] == 12345
        assert params["event_uuid"] == "test-uuid-123"
        assert params["min_timestamp"] == client._test_start_date.isoformat()
        assert mock_sync_execute.call_args[1]["team_id"] == 12345

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_returns_captured_event_when_found(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = [
            (
                uuid.UUID("00000000-0000-0000-0000-000000000123"),
                "test_event",
                "user_456",
                {"key": "value"},
                datetime(2024, 1, 1),
            )
        ]

        result = client._fetch_event_by_uuid("uuid-123")

        assert result is not None
        assert isinstance(result, CapturedEvent)
        assert result.uuid == "00000000-0000-0000-0000-000000000123"
        assert result.event == "test_event"
        assert result.distinct_id == "user_456"
        assert result.properties == {"key": "value"}

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_returns_none_when_not_found(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = []

        result = client._fetch_event_by_uuid("nonexistent-uuid")

        assert result is None

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_parses_json_string_properties(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = [
            (
                uuid.UUID("00000000-0000-0000-0000-000000000123"),
                "test_event",
                "user_456",
                '{"key": "value"}',
                datetime(2024, 1, 1),
            )
        ]

        result = client._fetch_event_by_uuid("uuid-123")

        assert result is not None
        assert result.properties == {"key": "value"}


class TestFetchPersonByDistinctId:
    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_sends_correct_clickhouse_query(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = []

        client._fetch_person_by_distinct_id("user_123")

        mock_sync_execute.assert_called_once()
        query = mock_sync_execute.call_args[0][0]
        params = mock_sync_execute.call_args[0][1]

        assert "FROM person FINAL AS p" in query
        assert "JOIN person_distinct_id2 FINAL AS pdi" in query
        assert "pdi.distinct_id = %(distinct_id)s" in query
        assert "pdi.is_deleted = 0" in query
        assert "p.is_deleted = 0" in query
        assert params["team_id"] == 12345
        assert params["distinct_id"] == "user_123"

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_returns_person_when_found(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = [
            (
                uuid.UUID("00000000-0000-0000-0000-000000000abc"),
                {"email": "test@example.com", "name": "Test"},
                datetime(2024, 1, 1),
            )
        ]

        result = client._fetch_person_by_distinct_id("user_123")

        assert result is not None
        assert isinstance(result, Person)
        assert result.id == "00000000-0000-0000-0000-000000000abc"
        assert result.properties == {"email": "test@example.com", "name": "Test"}

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_returns_none_when_not_found(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = []

        result = client._fetch_person_by_distinct_id("nonexistent-user")

        assert result is None

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_filters_out_deleted_persons_and_distinct_ids(
        self, mock_sync_execute: MagicMock, client: PostHogClient
    ) -> None:
        """Verify the query includes is_deleted = 0 filters for both person and person_distinct_id2.

        Both tables are ReplacingMergeTree — without these filters, soft-deleted rows
        can be returned before ClickHouse merges parts.
        """
        mock_sync_execute.return_value = []

        client._fetch_person_by_distinct_id("user_123")

        query = mock_sync_execute.call_args[0][0]
        assert "p.is_deleted = 0" in query, "Missing is_deleted filter on person table"
        assert "pdi.is_deleted = 0" in query, "Missing is_deleted filter on person_distinct_id2 table"


class TestFetchEventsByPersonId:
    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_resolves_via_person_distinct_id2_final(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = []

        client._fetch_events_by_person_id("test-person-id", expected_event_uuids={"some-uuid"})

        mock_sync_execute.assert_called_once()
        query = mock_sync_execute.call_args[0][0]
        params = mock_sync_execute.call_args[0][1]

        assert "person_distinct_id2 FINAL" in query
        assert "distinct_id IN" in query
        assert "timestamp >= %(min_timestamp)s" in query
        assert params["person_id"] == "test-person-id"
        assert params["min_timestamp"] == client._test_start_date.isoformat()

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_returns_none_when_not_all_uuids_found(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        mock_sync_execute.return_value = [
            (uuid.UUID("00000000-0000-0000-0000-000000000001"), "ev", "u", {}, datetime(2024, 1, 1))
        ]

        result = client._fetch_events_by_person_id(
            "person-1", expected_event_uuids={"00000000-0000-0000-0000-000000000001", "missing-uuid"}
        )

        assert result is None

    @patch("posthog.temporal.ingestion_acceptance_test.client.sync_execute")
    def test_returns_events_when_all_uuids_found(self, mock_sync_execute: MagicMock, client: PostHogClient) -> None:
        uuid1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
        uuid2 = uuid.UUID("00000000-0000-0000-0000-000000000002")
        mock_sync_execute.return_value = [
            (uuid1, "ev1", "u1", {"k": "v1"}, datetime(2024, 1, 1)),
            (uuid2, "ev2", "u2", {"k": "v2"}, datetime(2024, 1, 2)),
        ]

        result = client._fetch_events_by_person_id("person-1", expected_event_uuids={str(uuid1), str(uuid2)})

        assert result is not None
        assert len(result) == 2
        assert result[0].uuid == str(uuid1)
        assert result[1].uuid == str(uuid2)


class TestTimestampFiltering:
    def test_client_stores_test_start_date(self, client: PostHogClient) -> None:
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)

        assert client._test_start_date == yesterday
