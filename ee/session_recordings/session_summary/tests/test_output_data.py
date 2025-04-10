from datetime import datetime
import pytest
from openai.types.chat.chat_completion import ChatCompletion, Choice, ChatCompletionMessage
from ee.session_recordings.ai.output_data import load_raw_session_summary_from_llm_content


@pytest.fixture
def mock_valid_llm_yaml_response() -> str:
    return """```yaml
summary: User logged in and created a new project
key_events:
  - description: User clicked login button
    error: false
    tags:
      where: ["login page"]
      what: ["authentication"]
    importance: 0.8
    event_id: abc123
  - description: User created new project
    error: false
    tags:
      where: ["dashboard"]
      what: ["project creation"]
    importance: 0.9
    event_id: def456
```"""


@pytest.fixture
def mock_chat_completion(mock_valid_llm_yaml_response: str) -> ChatCompletion:
    return ChatCompletion(
        id="test_id",
        model="test_model",
        object="chat.completion",
        created=int(datetime.now().timestamp()),
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(
                    content=mock_valid_llm_yaml_response,
                    role="assistant",
                ),
            )
        ],
    )


def test_load_raw_session_summary_success(mock_chat_completion: ChatCompletion) -> None:
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


def test_load_raw_session_summary_no_content(mock_chat_completion: ChatCompletion) -> None:
    mock_chat_completion.choices[0].message.content = None
    session_id = "test_session"
    with pytest.raises(ValueError, match=f"No LLM content found when summarizing session_id {session_id}"):
        load_raw_session_summary_from_llm_content(mock_chat_completion, [], session_id)


def test_load_raw_session_summary_invalid_yaml(mock_chat_completion: ChatCompletion) -> None:
    mock_chat_completion.choices[0].message.content = """```yaml
        invalid: yaml: content:
        - not properly formatted
    ```"""
    session_id = "test_session"
    with pytest.raises(
        ValueError, match=f"Error loading YAML content into JSON when summarizing session_id {session_id}"
    ):
        load_raw_session_summary_from_llm_content(mock_chat_completion, [], session_id)


def test_load_raw_session_summary_invalid_schema(mock_chat_completion: ChatCompletion) -> None:
    mock_chat_completion.choices[0].message.content = """```yaml
    summary: Just a summary without key events
    ```"""
    session_id = "test_session"
    with pytest.raises(
        ValueError, match=f"Error validating LLM output against the schema when summarizing session_id {session_id}"
    ):
        load_raw_session_summary_from_llm_content(mock_chat_completion, [], session_id)


def test_load_raw_session_summary_hallucinated_event(mock_chat_completion: ChatCompletion) -> None:
    allowed_event_ids = ["abc123"]  # Missing def456
    session_id = "test_session"
    with pytest.raises(ValueError, match=f"LLM hallucinated event_id def456 when summarizing session_id {session_id}"):
        load_raw_session_summary_from_llm_content(mock_chat_completion, allowed_event_ids, session_id)
