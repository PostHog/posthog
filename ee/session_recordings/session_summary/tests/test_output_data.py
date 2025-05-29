from datetime import UTC, datetime
from typing import Any
import pytest
from openai.types.chat.chat_completion import ChatCompletion
from ee.session_recordings.ai.output_data import (
    RawSessionSummarySerializer,
    calculate_time_since_start,
    enrich_raw_session_summary_with_events_meta,
    load_raw_session_summary_from_llm_content,
)


class TestLoadRawSessionSummary:
    def test_load_raw_session_summary_success(self, mock_chat_completion: ChatCompletion) -> None:
        allowed_event_ids = ["abc123", "def456"]
        session_id = "test_session"
        result = load_raw_session_summary_from_llm_content(mock_chat_completion, allowed_event_ids, session_id)
        # Ensure the LLM output is valid
        assert result.is_valid()
        assert result.data["summary"] == "User logged in and created a new project"
        assert len(result.data["key_events"]) == 2
        # Ensure the event processing is valid
        first_event = result.data["key_events"][0]
        assert first_event["description"] == "User clicked login button"
        assert first_event["error"] is False
        assert first_event["tags"]["where"] == ["login page"]
        assert first_event["tags"]["what"] == ["authentication"]
        assert first_event["importance"] == 0.8
        assert first_event["event_id"] == "abc123"

    def test_load_raw_session_summary_no_content(self, mock_chat_completion: ChatCompletion) -> None:
        mock_chat_completion.choices[0].message.content = None
        session_id = "test_session"
        with pytest.raises(ValueError, match=f"No LLM content found when summarizing session_id {session_id}"):
            load_raw_session_summary_from_llm_content(mock_chat_completion, [], session_id)

    def test_load_raw_session_summary_invalid_yaml(self, mock_chat_completion: ChatCompletion) -> None:
        mock_chat_completion.choices[0].message.content = """```yaml
            invalid: yaml: content:
            - not properly formatted
        ```"""
        session_id = "test_session"
        with pytest.raises(
            ValueError, match=f"Error loading YAML content into JSON when summarizing session_id {session_id}"
        ):
            load_raw_session_summary_from_llm_content(mock_chat_completion, [], session_id)

    def test_load_raw_session_summary_invalid_schema(self, mock_chat_completion: ChatCompletion) -> None:
        mock_chat_completion.choices[0].message.content = """```yaml
        summary: Just a summary without key events
        ```"""
        session_id = "test_session"
        with pytest.raises(
            ValueError, match=f"Error validating LLM output against the schema when summarizing session_id {session_id}"
        ):
            load_raw_session_summary_from_llm_content(mock_chat_completion, [], session_id)

    def test_load_raw_session_summary_hallucinated_event(self, mock_chat_completion: ChatCompletion) -> None:
        allowed_event_ids = ["abc123"]  # Missing def456
        session_id = "test_session"
        with pytest.raises(
            ValueError, match=f"LLM hallucinated event_id def456 when summarizing session_id {session_id}"
        ):
            load_raw_session_summary_from_llm_content(mock_chat_completion, allowed_event_ids, session_id)


@pytest.mark.parametrize(
    "event_time,start_time,expected",
    [
        ("2024-03-01T12:00:02Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 2000),  # 2 seconds after
        ("2024-03-01T12:00:00Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 0),  # same time
        ("2024-03-01T11:59:59Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 0),  # 1 second before (clamped to 0)
        (None, datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), None),  # no event time
        ("2024-03-01T12:00:02Z", None, None),  # no start time
        ("2024-03-01T13:00:00Z", datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC), 3600000),  # 1 hour after
    ],
)
def test_calculate_time_since_start(event_time: str, start_time: datetime, expected: int) -> None:
    result = calculate_time_since_start(event_time, start_time)
    assert result == expected


class TestEnrichRawSessionSummary:
    @pytest.fixture
    def mock_raw_session_summary(self, mock_chat_completion: ChatCompletion) -> RawSessionSummarySerializer:
        return load_raw_session_summary_from_llm_content(mock_chat_completion, ["abc123", "def456"], "test_session")

    @pytest.fixture
    def mock_events_mapping(self) -> dict[str, list[Any]]:
        return {
            "abc123": [
                "$autocapture",
                "2024-03-01T12:00:02Z",
                "",
                ["Log in"],
                ["button"],
                "window_1",
                "url_1",
                "click",
                "abc123",
            ],
            "def456": [
                "$autocapture",
                "2024-03-01T12:00:05Z",
                "",
                ["Submit"],
                ["form"],
                "window_1",
                "url_2",
                "submit",
                "def456",
            ],
        }

    @pytest.fixture
    def mock_events_columns(self) -> list[str]:
        return [
            "event",
            "timestamp",
            "elements_chain_href",
            "elements_chain_texts",
            "elements_chain_elements",
            "$window_id",
            "$current_url",
            "$event_type",
            "event_id",
        ]

    @pytest.fixture
    def mock_url_mapping_reversed(self) -> dict[str, str]:
        return {
            "url_1": "http://localhost:8010/login",
            "url_2": "http://localhost:8010/signup",
        }

    @pytest.fixture
    def mock_window_mapping_reversed(self) -> dict[str, str]:
        return {
            "window_1": "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
        }

    def test_enrich_raw_session_summary_success(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
    ) -> None:
        session_start_time = datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC)
        session_id = "test_session"
        result = enrich_raw_session_summary_with_events_meta(
            mock_raw_session_summary,
            mock_events_mapping,
            mock_events_columns,
            mock_url_mapping_reversed,
            mock_window_mapping_reversed,
            session_start_time,
            session_id,
        )
        # Ensure the enriched content is valid
        assert result.is_valid()
        assert result.data["summary"] == mock_raw_session_summary.data["summary"]
        assert len(result.data["key_events"]) == 2
        # Check first event enrichment
        first_event = result.data["key_events"][0]
        assert first_event["event"] == "$autocapture"
        assert first_event["timestamp"] == "2024-03-01T12:00:02Z"
        assert first_event["milliseconds_since_start"] == 2000
        assert first_event["window_id"] == "0195ed81-7519-7595-9221-8bb8ddb1fdcc"
        assert first_event["current_url"] == "http://localhost:8010/login"
        assert first_event["event_type"] == "click"
        # Check events are sorted by timestamp (comparing as there are just two events)
        assert (
            result.data["key_events"][0]["milliseconds_since_start"]
            < result.data["key_events"][1]["milliseconds_since_start"]
        )

    def test_enrich_raw_session_summary_missing_event(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
    ) -> None:
        # Remove one event from mapping
        del mock_events_mapping["abc123"]
        session_start_time = datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC)
        session_id = "test_session"
        with pytest.raises(
            ValueError, match=f"Mapping data for event_id abc123 not found when summarizing session_id {session_id}"
        ):
            enrich_raw_session_summary_with_events_meta(
                mock_raw_session_summary,
                mock_events_mapping,
                mock_events_columns,
                mock_url_mapping_reversed,
                mock_window_mapping_reversed,
                session_start_time,
                session_id,
            )

    def test_enrich_raw_session_summary_invalid_schema(
        self,
        mock_raw_session_summary: RawSessionSummarySerializer,
        mock_events_mapping: dict[str, list[Any]],
        mock_events_columns: list[str],
        mock_url_mapping_reversed: dict[str, str],
        mock_window_mapping_reversed: dict[str, str],
    ) -> None:
        # Change type of the event to the unsupported one to cause schema validation error
        mock_events_mapping["abc123"][0] = set()
        session_start_time = datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC)
        session_id = "test_session"
        with pytest.raises(
            ValueError,
            match=f"Error validating enriched content against the schema when summarizing session_id {session_id}",
        ):
            enrich_raw_session_summary_with_events_meta(
                mock_raw_session_summary,
                mock_events_mapping,
                mock_events_columns,
                mock_url_mapping_reversed,
                mock_window_mapping_reversed,
                session_start_time,
                session_id,
            )
