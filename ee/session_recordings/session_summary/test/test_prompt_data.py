from ee.session_recordings.ai.prompt_data import SessionSummaryPromptData, SessionSummaryMetadata
from typing import Any
import pytest
from datetime import datetime
from ee.session_recordings.session_summary.utils import prepare_datetime


@pytest.mark.parametrize(
    "event,expected",
    [
        # Basic types
        (["test", 123, True], "15d1559b"),
        # With datetime
        ([datetime(2024, 3, 20, 15, 30, 45), "test"], "08ea66e0"),
        # With None values
        (["test", None, "value"], "8d58a0fb"),
        # Empty list
        ([], "e3b0c442"),
        # List with empty string, should be the same
        ([""], "e3b0c442"),
    ],
)
def test_get_deterministic_hex_length(event: list[Any], expected: str) -> None:
    result = SessionSummaryPromptData._get_deterministic_hex(event)
    assert result == expected


def test_simplify_url() -> None:
    prompt_data = SessionSummaryPromptData()
    # Ignore empty values
    assert prompt_data._simplify_url(None) is None
    assert prompt_data._simplify_url("") is None
    # First URL gets url_1
    assert prompt_data._simplify_url("https://example.com") == "url_1"
    # Same URL returns same mapping
    assert prompt_data._simplify_url("https://example.com") == "url_1"
    # Different URLs get incremented numbers
    assert prompt_data._simplify_url("https://example.org") == "url_2"
    assert prompt_data._simplify_url("https://another.com") == "url_3"
    # Verify mappings are preserved
    assert prompt_data.url_mapping == {
        "https://example.com": "url_1",
        "https://example.org": "url_2",
        "https://another.com": "url_3",
    }


def test_simplify_window_id() -> None:
    prompt_data = SessionSummaryPromptData()
    # Ignore empty values
    assert prompt_data._simplify_window_id(None) is None
    assert prompt_data._simplify_window_id("") is None
    # First window gets window_1
    assert prompt_data._simplify_window_id("abc-123-xyz") == "window_1"
    # Same window ID returns same mapping
    assert prompt_data._simplify_window_id("abc-123-xyz") == "window_1"
    # Different window IDs get incremented numbers
    assert prompt_data._simplify_window_id("def-456-uvw") == "window_2"
    assert prompt_data._simplify_window_id("ghi-789-rst") == "window_3"
    # Verify mappings are preserved
    assert prompt_data.window_id_mapping == {
        "abc-123-xyz": "window_1",
        "def-456-uvw": "window_2",
        "ghi-789-rst": "window_3",
    }


@pytest.fixture
def _raw_metadata() -> dict[str, Any]:
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        # Anonymized distinct_id for testing
        "distinct_id": "EheLkWe3eZBtiru9xSJgq2SNWoD8YHQnKu0FWkMDZMU",
        "viewed": True,
        "viewers": [],
        "recording_duration": 5323,
        "active_seconds": 1947,
        "inactive_seconds": 3375,
        "start_time": "2025-04-01T11:13:33.315000Z",
        "end_time": "2025-04-01T12:42:16.671000Z",
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


def test_prepare_metadata(_raw_metadata: dict[str, Any]) -> None:
    prompt_data = SessionSummaryPromptData()
    metadata = prompt_data._prepare_metadata(_raw_metadata)
    assert isinstance(metadata, SessionSummaryMetadata)
    # Check all fields are preserved correctly
    assert metadata.start_time == prepare_datetime("2025-04-01T11:13:33.315000Z")
    assert metadata.end_time == prepare_datetime("2025-04-01T12:42:16.671000Z")
    assert metadata.active_seconds == 1947
    assert metadata.inactive_seconds == 3375
    assert metadata.click_count == 679
    assert metadata.keypress_count == 668
    assert metadata.mouse_activity_count == 6629
    assert metadata.console_log_count == 4
    assert metadata.console_warn_count == 144
    assert metadata.console_error_count == 114
    assert metadata.start_url == "https://us.example.com/project/11111/insights/aAaAAAaA"
    assert metadata.activity_score is None


@pytest.fixture
def _raw_events() -> list[list[Any]]:
    return [
        [
            "client_request_failure",
            datetime(2025, 3, 31, 18, 40, 39, 302000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            None,
        ],
        [
            "$pageview",
            datetime(2025, 3, 31, 18, 40, 39, 200000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            None,
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 40, 43, 645000),
            "",
            ["Log in"],
            ["button", "form"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            "click",
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 40, 43, 647000),
            "",
            [],
            ["form"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            "submit",
        ],
        [
            "$web_vitals",
            datetime(2025, 3, 31, 18, 40, 44, 251000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            None,
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 40, 58, 699000),
            "/signup",
            ["Create an account"],
            ["a"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            "click",
        ],
        [
            "$pageview",
            datetime(2025, 3, 31, 18, 40, 58, 710000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup",
            None,
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 41, 5, 459000),
            "",
            ["Continue"],
            ["button", "form"],
            "0235ed82-1519-7595-9221-8bb8ddb1fdc4",
            "http://localhost:8010/signup",
            "click",
        ],
    ]


def test_load_session_data(_raw_events: list[list[Any]], _raw_metadata: dict[str, Any]) -> None:
    prompt_data = SessionSummaryPromptData()
    raw_columns = [
        "event",
        "timestamp",
        "elements_chain_href",
        "elements_chain_texts",
        "elements_chain_elements",
        "$window_id",
        "$current_url",
        "$event_type",
    ]
    session_id = "test_session_id"
    events_mapping = prompt_data.load_session_data(_raw_events, _raw_metadata, raw_columns, session_id)
    # Verify columns are set correctly with event_id added
    assert prompt_data.columns == [*raw_columns, "event_id"]
    # Verify window_id mapping
    assert len(prompt_data.window_id_mapping) == 2
    assert list(prompt_data.window_id_mapping.keys()) == [
        "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
        "0235ed82-1519-7595-9221-8bb8ddb1fdc4",
    ]
    assert list(prompt_data.window_id_mapping.values()) == ["window_1", "window_2"]
    # Verify URL mapping
    assert len(prompt_data.url_mapping) == 2
    assert list(prompt_data.url_mapping.keys()) == [
        "http://localhost:8010/login?next=/",
        "http://localhost:8010/signup",
    ]
    assert list(prompt_data.url_mapping.values()) == ["url_1", "url_2"]
    # Verify events are processed correctly and not filtered out (yet)
    assert len(prompt_data.results) == len(_raw_events)  # No duplicate events in sample
    assert len(events_mapping) == len(_raw_events)
    # Verify event structure
    first_event = prompt_data.results[0]
    assert len(first_event) == len(raw_columns) + 1  # +1 for event_id
    assert first_event[0] == "client_request_failure"  # event type preserved
    assert first_event[5] == "window_1"  # window_id mapped
    assert first_event[6] == "url_1"  # url mapped
    assert isinstance(first_event[-1], str)  # event_id is hex string
