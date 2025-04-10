from datetime import UTC, datetime
import pytest
from openai.types.chat.chat_completion import ChatCompletion
from ee.session_recordings.ai.output_data import calculate_time_since_start, load_raw_session_summary_from_llm_content


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
