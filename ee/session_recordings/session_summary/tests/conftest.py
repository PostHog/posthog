from typing import Any
import pytest
from datetime import datetime
from openai.types.chat.chat_completion import ChatCompletion, Choice, ChatCompletionMessage

from ee.session_recordings.session_summary.input_data import COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT
from ee.session_recordings.session_summary.prompt_data import SessionSummaryMetadata, SessionSummaryPromptData


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
            description: 'First significant action in this segment'
            abandonment: false
            confusion: false
            exception: null
          - event_id: 'defg4567'
            description: 'Second action in this segment'
            abandonment: false
            confusion: false
            exception: null
    - segment_index: 1
      events:
          - event_id: 'ghij7890'
            description: 'Significant action in this segment'
            abandonment: false
            confusion: false
            exception: null
          - event_id: 'mnop3456'
            description: 'User attempted to perform an action but encountered an error'
            abandonment: false
            confusion: true
            exception: 'blocking'
          - event_id: 'stuv9012'
            description: 'Final action in this chronological segment'
            abandonment: true
            confusion: false
            exception: null

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
def mock_loaded_llm_json_response() -> dict[str, Any]:
    """
    Exact YAML response, but converted into JSON.
    """
    return {
        "segments": [
            {"index": 0, "start_event_id": "abcd1234", "end_event_id": "vbgs1287", "name": "Example Segment"},
            {"index": 1, "start_event_id": "gfgz6242", "end_event_id": "stuv9012", "name": "Another Example Segment"},
        ],
        "key_actions": [
            {
                "segment_index": 0,
                "events": [
                    {
                        "event_id": "abcd1234",
                        "description": "First significant action in this segment",
                        "abandonment": False,
                        "confusion": False,
                        "exception": None,
                    },
                    {
                        "event_id": "defg4567",
                        "description": "Second action in this segment",
                        "abandonment": False,
                        "confusion": False,
                        "exception": None,
                    },
                ],
            },
            {
                "segment_index": 1,
                "events": [
                    {
                        "event_id": "ghij7890",
                        "description": "Significant action in this segment",
                        "abandonment": False,
                        "confusion": False,
                        "exception": None,
                    },
                    {
                        "event_id": "mnop3456",
                        "description": "User attempted to perform an action but encountered an error",
                        "abandonment": False,
                        "confusion": True,
                        "exception": "blocking",
                    },
                    {
                        "event_id": "stuv9012",
                        "description": "Final action in this chronological segment",
                        "abandonment": True,
                        "confusion": False,
                        "exception": None,
                    },
                ],
            },
        ],
        "segment_outcomes": [
            {"segment_index": 0, "success": True, "summary": "Detailed description incorporating key action insights"},
            {
                "segment_index": 1,
                "success": False,
                "summary": "Description highlighting encountered failures and their impact",
            },
        ],
        "session_outcome": {
            "success": True,
            "description": "Concise session outcome description focusing on conversion attempts, feature usage, and critical issues",
        },
    }


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
def mock_session_metadata(mock_raw_metadata: dict[str, Any]) -> SessionSummaryMetadata:
    return SessionSummaryPromptData()._prepare_metadata(mock_raw_metadata)


@pytest.fixture
def mock_raw_events_columns() -> list[str]:
    """
    Columns from DB
    """
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
        "$exception_types",
        "$exception_sources",
        "$exception_values",
        "$exception_fingerprint_record",
        "$exception_functions",
    ]


@pytest.fixture
def mock_filtered_events_columns(mock_raw_events_columns: list[str]) -> list[str]:
    """
    Columns after adding more context and filtering out columns that are not needed for the LLM
    """
    return [col for col in mock_raw_events_columns if col not in COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT]


@pytest.fixture
def mock_events_columns(mock_filtered_events_columns: list[str]) -> list[str]:
    """
    Columns that are used in the LLM.
    """
    return [
        *mock_filtered_events_columns,
        "event_id",
        "event_index",
    ]


@pytest.fixture
def mock_valid_event_ids() -> list[str]:
    return ["abcd1234", "defg4567", "vbgs1287", "gfgz6242", "ghij7890", "mnop3456", "stuv9012"]


@pytest.fixture
def mock_raw_events() -> list[tuple[Any, ...]]:
    """
    Raw events from DB
    """
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
            [],
            [],
            [],
            [],
            [],
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
            [],
            [],
            [],
            [],
            [],
        ),
        (
            "$pageview",  # vbgs1287 - end of segment 0
            datetime(2025, 3, 31, 18, 40, 45, 251000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup",
            None,
            [],
            "",
            [],
            [],
            [],
            [],
            [],
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
            [],
            [],
            [],
            [],
            [],
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
            [],
            [],
            [],
            [],
            [],
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
            [],
            [],
            [],
            [],
            [],
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
            [],
            [],
            [],
            [],
            [],
        ),
    ]


@pytest.fixture
def mock_filtered_events(
    mock_raw_events: list[tuple[Any, ...]],
    mock_raw_events_columns: list[str],
    mock_filtered_events_columns: list[str],
) -> list[tuple[Any, ...]]:
    """
    Filtered events that only include columns that are needed for the LLM
    """
    column_indices = [mock_raw_events_columns.index(col) for col in mock_filtered_events_columns]
    return [tuple(event[i] for i in column_indices) for event in mock_raw_events]


@pytest.fixture
def mock_events_mapping(
    mock_raw_events: list[tuple[Any, ...]],
    mock_url_mapping: dict[str, str],
    mock_window_mapping: dict[str, str],
    mock_valid_event_ids: list[str],
) -> dict[str, list[Any]]:
    events_mapping = {}
    for event_index, (event_id, raw_event) in enumerate(zip(mock_valid_event_ids, mock_raw_events)):
        (
            event_type,
            timestamp,
            href,
            texts,
            elements,
            window_id,
            url,
            action_type,
            elements_chain_ids,
            elements_chain,
            exception_types,
            exception_sources,
            exception_values,
            exception_fingerprint_record,
            exception_functions,
        ) = raw_event
        # Some columns don't go into the mapping, as they are filtered out to avoid sending too much data to the LLM
        events_mapping[event_id] = [
            event_type,
            timestamp.isoformat() + "Z",
            href,
            texts,
            elements,
            mock_window_mapping[window_id],
            mock_url_mapping[url],
            action_type,
            elements_chain_ids,
            exception_types,
            exception_values,
            event_id,
            event_index,
        ]
    return events_mapping


@pytest.fixture
def mock_url_mapping_reversed() -> dict[str, str]:
    return {
        "url_1": "http://localhost:8010/login",
        "url_2": "http://localhost:8010/signup",
        "url_3": "http://localhost:8010/signup/error",
    }


@pytest.fixture
def mock_url_mapping(mock_url_mapping_reversed: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in mock_url_mapping_reversed.items()}


@pytest.fixture
def mock_window_mapping_reversed() -> dict[str, str]:
    return {
        "window_1": "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
    }


@pytest.fixture
def mock_window_mapping(mock_window_mapping_reversed: dict[str, str]) -> dict[str, str]:
    return {v: k for k, v in mock_window_mapping_reversed.items()}
