from typing import Any
import pytest
from datetime import datetime
from openai.types.chat.chat_completion import ChatCompletion, Choice, ChatCompletionMessage


@pytest.fixture
def mock_valid_llm_yaml_response() -> str:
    return """```yaml
segments:
    - index: 0
      start_event_id: 'abcd1234'
      end_event_id: 'vbgs1287'
      name: 'Example Segment'
    - index: 1
      start_event_id: 'gfgz6242'
      end_event_id: 'stuv9012'
      name: 'Another Example Segment'

key_actions:
    - segment_index: 0
      events:
          - event_id: 'abcd1234'
            failure: false
            description: 'First significant action in this segment'
          - event_id: 'defg4567'
            failure: false
            description: 'Second action in this segment'
    - segment_index: 1
      events:
          - event_id: 'ghij7890'
            failure: false
            description: 'Significant action in this segment'
          - event_id: 'mnop3456'
            failure: true
            description: 'User attempted to perform an action but encountered an error'
          - event_id: 'stuv9012'
            failure: false
            description: 'Final action in this chronological segment'

segment_outcomes:
    - segment_index: 0
      success: true
      summary: 'Detailed description incorporating key action insights'
    - segment_index: 1
      success: false
      summary: 'Description highlighting encountered failures and their impact'

session_outcome:
    success: true
    description: 'Concise session outcome description focusing on conversion attempts, feature usage, and critical issues'
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


@pytest.fixture
def mock_raw_metadata() -> dict[str, Any]:
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        # Anonymized distinct_id for testing
        "distinct_id": "EheLkWe3eZBtiru9xSJgq2SNWoD8YHQnKu0FWkMDZMU",
        "viewed": True,
        "viewers": [],
        "recording_duration": 5323,
        "active_seconds": 1947,
        "inactive_seconds": 3375,
        "start_time": "2025-03-31T18:40:32.302000Z",
        "end_time": "2025-03-31T18:54:15.789000Z",
        "click_count": 679,
        "keypress_count": 668,
        "mouse_activity_count": 6629,
        "console_log_count": 4,
        "console_warn_count": 144,
        "console_error_count": 114,
        "start_url": "https://us.example.com/project/11111/insights/aAaAAAaA",
        "storage": "object_storage",
        "snapshot_source": "web",
        "ongoing": None,
        "activity_score": None,
    }


@pytest.fixture
def mock_events_columns() -> list[str]:
    return [
        "event",
        "timestamp",
        "elements_chain_href",
        "elements_chain_texts",
        "elements_chain_elements",
        "$window_id",
        "$current_url",
        "$event_type",
        "elements_chain_ids",
        "elements_chain",
        # Added later through enrichment
        "event_id",
        "event_index",
    ]


@pytest.fixture
def mock_raw_events() -> list[tuple[Any, ...]]:
    return [
        # First segment events
        (
            "$autocapture",  # abcd1234 - start of segment 0
            datetime(2025, 3, 31, 18, 40, 39, 302000),
            "",
            ["Log in"],
            ["button"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login",
            "click",
            [],
            "",
        ),
        (
            "$autocapture",  # defg4567
            datetime(2025, 3, 31, 18, 40, 43, 645000),
            "",
            ["Submit"],
            ["form"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login",
            "submit",
            [],
            "",
        ),
        (
            "$pageview",  # vbgs1287 - end of segment 0
            datetime(2025, 3, 31, 18, 40, 44, 251000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup",
            None,
            [],
            "",
        ),
        # Second segment events
        (
            "$autocapture",  # gfgz6242 - start of segment 1
            datetime(2025, 3, 31, 18, 40, 58, 699000),
            "",
            ["Create"],
            ["button"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup",
            "click",
            [],
            "",
        ),
        (
            "$autocapture",  # ghij7890
            datetime(2025, 3, 31, 18, 41, 5, 459000),
            "",
            ["Continue"],
            ["button"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup",
            "click",
            [],
            "",
        ),
        (
            "$autocapture",  # mnop3456
            datetime(2025, 3, 31, 18, 41, 10, 123000),
            "",
            ["Submit"],
            ["form"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup/error",
            "submit",
            [],
            "",
        ),
        (
            "$autocapture",  # stuv9012 - end of segment 1
            datetime(2025, 3, 31, 18, 41, 15, 789000),
            "",
            ["Try Again"],
            ["button"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup/error",
            "click",
            [],
            "",
        ),
    ]
