from typing import Any
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
import json

from ee.session_recordings.session_summary.input_data import (
    COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT,
    _skip_event_without_valid_context,
    _get_improved_elements_chain_texts,
    _get_improved_elements_chain_elements,
    add_context_and_filter_events,
    get_session_events,
    _skip_exception_without_valid_context,
)
from posthog.session_recordings.models.metadata import RecordingMetadata


@pytest.fixture
def mock_event_indexes(mock_raw_events_columns: list[str]) -> dict[str, int]:
    return {col: idx for idx, col in enumerate(mock_raw_events_columns)}


@pytest.mark.parametrize(
    "event_tuple,expected_skip",
    [
        # Should skip autocapture event with no context
        (("$autocapture", None, "", [], [], None, None, "click", [], "", [], [], [], [], [], []), True),
        # Should not skip autocapture event with text context
        (("$autocapture", None, "", ["Click me"], [], None, None, "click", [], "", [], [], [], [], [], []), False),
        # Should not skip autocapture event with element context
        (("$autocapture", None, "", [], ["button"], None, None, "click", [], "", [], [], [], [], [], []), False),
        # Should skip custom event with no context and simple name
        (("click", None, "", [], [], None, None, "click", [], "", [], [], [], [], [], []), True),
        # Should not skip custom event with context
        (("click", None, "", ["Click me"], [], None, None, "click", [], "", [], [], [], [], [], []), False),
        # Should not skip custom event with complex name
        (("user.clicked_button", None, "", [], [], None, None, "click", [], "", [], [], [], [], [], []), False),
    ],
)
def test_skip_event_without_context(
    mock_event_indexes: dict[str, int], event_tuple: tuple[Any, ...], expected_skip: bool
):
    assert _skip_event_without_valid_context(list(event_tuple), mock_event_indexes) is expected_skip


def test_get_improved_elements_chain_texts():
    # Should extract text and aria-label
    chain = """
    span.ButtonTextstyles__StyledButtonText-sc-1smg0pq-0.Text-sc-1k5lnf-0.bPcimM.jsLoCB:text=""Submit""nth-child=""2""nth-of-type=""2""attr__aria-label=""Submit form""attr__variant=""V2BrandPurpleSolid
    """
    assert _get_improved_elements_chain_texts(chain, []) == ["Submit", "Submit form"]
    # Should remove duplicates
    chain = """
    span.ButtonTextstyles__StyledButtonText-sc-1smg0pq-0.Text-sc-1k5lnf-0.bPcimM.jsLoCB:text=""Submit""nth-child=""2""nth-of-type=""2""attr__aria-label=""Submit""attr__variant=""V2BrandPurpleSolid
    """
    assert _get_improved_elements_chain_texts(chain, []) == ["Submit"]
    # Should keep current texts if longer
    chain = 'button:text="Submit"'
    current_texts = ["Submit", "Additional context"]
    assert _get_improved_elements_chain_texts(chain, current_texts) == current_texts
    # Should handle empty chain
    assert _get_improved_elements_chain_texts("", []) == []


def test_get_improved_elements_chain_elements():
    # Should attach type to input elements
    chain = 'input:attr__type="text"'
    assert _get_improved_elements_chain_elements(chain, []) == ['input[type="text"]']
    # Should not attach button type
    chain = 'button:attr__type="button"'
    assert _get_improved_elements_chain_elements(chain, []) == ["button"]
    # Should handle multiple elements
    chain = 'input:attr__type="text";button:attr__type="button";input:attr__type="password"'
    assert _get_improved_elements_chain_elements(chain, []) == [
        'input[type="text"]',
        "button",
        'input[type="password"]',
    ]
    # Should remove duplicates
    chain = 'input:attr__type="text";input:attr__type="text"'
    assert _get_improved_elements_chain_elements(chain, []) == ['input[type="text"]']
    # Should keep current elements if longer
    chain = 'input:attr__type="text"'
    current_elements = ["input[type='text']", "additional_element"]
    assert _get_improved_elements_chain_elements(chain, current_elements) == current_elements


@pytest.mark.parametrize(
    "input_event,expected_event,should_keep",
    [
        # Event with context should be kept and unchanged (except removing excessive columns)
        (
            (
                "$autocapture",
                None,
                "",
                ["Click me"],
                [],
                None,
                None,
                "click",
                [],
                "button:text='Click me'",
                [],
                [],
                [],
                [],
                [],
                [],
            ),
            (
                "$autocapture",
                None,
                "",
                ["Click me"],
                ["button"],
                None,
                None,
                "click",
                [],
                [],
                [],
            ),
            True,
        ),
        # Event without context should be filtered out
        (
            (
                "$autocapture",
                None,
                "",
                [],
                [],
                None,
                None,
                "click",
                [],
                "",
                [],
                [],
                [],
                [],
                [],
                [],
            ),
            None,
            False,
        ),
        # Event with complex chain should have improved context
        (
            (
                "$autocapture",
                None,
                "",
                [],
                [],
                None,
                None,
                "click",
                [],
                '"svg.c_gray.80.d_flex.flex-sh_0:nth-child=""1""nth-of-type=""1""href=""/project/new""attr__fill=""none""attr__focusable=""false""attr__height=""24""attr__role=""img""attr__stroke-width=""1""attr__viewBox=""0 0 24 24""attr__width=""24""attr__class=""c_gray.80 d_flex flex-sh_0";button:text="Click me""attr__href=""/project/new"";a.[&:hover,_&:focus,_&:focus-visible,_&:focus-within,_&:active]:bg-c_gray.30.ai_center.bdr_100%.bg-c_gray.10.d_flex.flex-sh_0.h_47px.jc_center.trs_background-color_0.2s_ease-out.w_47px.white-space_nowrap:nth-child=""1""nth-of-type=""1""href=""/project/new""attr__aria-label=""Create project""',
                [],
                [],
                [],
                [],
                [],
                [],
            ),
            (
                "$autocapture",
                None,
                "",
                ["Click me", "Create project"],
                ["button", "a"],
                None,
                None,
                "click",
                [],
                [],
                [],
            ),
            True,
        ),
        # Event with complex name should be kept unchanged
        (
            (
                "user_clicked_button",
                None,
                "",
                [],
                [],
                None,
                None,
                "click",
                [],
                "",
                [],
                [],
                [],
                [],
                [],
                [],
            ),
            (
                "user_clicked_button",
                None,
                "",
                [],
                [],
                None,
                None,
                "click",
                [],
                [],
                [],
            ),
            True,
        ),
    ],
)
def test_add_context_and_filter_events(
    mock_event_indexes: dict[str, int],
    input_event: tuple[Any, ...],
    expected_event: tuple[Any, ...] | None,
    should_keep: bool,
):
    test_columns = list(mock_event_indexes.keys())
    updated_columns, updated_events = add_context_and_filter_events(test_columns, [input_event])

    # Check columns are updated (and columns excessive from LLM context are removed)
    assert len(updated_columns) == len(test_columns) - len(COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT)
    for column in COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT:
        assert column not in updated_columns

    # Check if event was kept or filtered out
    if should_keep:
        assert len(updated_events) == 1
        assert updated_events[0] == expected_event
    else:
        assert len(updated_events) == 0


@pytest.mark.parametrize(
    "pages_data,expected_count,expected_iterations,expected_error",
    [
        # Got less than requested (N=2), should stop
        (
            [
                [
                    (
                        "$autocapture",
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
                    )
                ]
            ],
            1,  # Got 1 event
            1,  # Called one page
            None,
        ),
        # Got exactly N (N=2), should try next page
        (
            [
                [
                    (
                        "$autocapture",
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
                        "$pageview",
                        datetime(2025, 3, 31, 18, 40, 44, 251000),
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
                ],
                # Second page is empty
                [],
            ],
            2,  # Got 2 events total
            2,  # Called two pages
            None,
        ),
        # Got exactly N (N=2), should try next page and get more events
        (
            [
                [
                    (
                        "$autocapture",
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
                        "$pageview",
                        datetime(2025, 3, 31, 18, 40, 44, 251000),
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
                ],
                # Second page has one more event
                [
                    (
                        "$autocapture",
                        datetime(2025, 3, 31, 18, 40, 49, 200000),
                        "",
                        ["Sign up"],
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
                ],
            ],
            3,  # Got 3 events total
            2,  # Called two pages
            None,
        ),
        # Got no events, should raise error
        (
            [None],
            0,
            1,  # Called once
            ValueError,
        ),
    ],
)
def test_get_paginated_session_events(
    mock_raw_metadata: dict[str, Any],
    mock_events_columns: list[str],
    mock_team: MagicMock,
    pages_data: list[list[tuple[Any, ...]] | None],
    expected_count: int,
    expected_iterations: int,
    expected_error: type[Exception] | None,
):
    items_per_page = 2
    max_pages = 3
    mock_metadata = RecordingMetadata(**mock_raw_metadata)  # type: ignore
    mock_columns = mock_events_columns
    # Prepare mock pages data (add columns to each page)
    processed_pages_data = [(mock_columns, events) if events is not None else (None, None) for events in pages_data]
    with (
        patch("ee.session_recordings.session_summary.input_data.SessionReplayEvents") as mock_replay_events,
        patch("ee.session_recordings.session_summary.input_data.get_team", return_value=mock_team),
    ):
        # Mock the SessionReplayEvents DB model to return different data for each page
        mock_instance = MagicMock()
        mock_replay_events.return_value = mock_instance
        mock_instance.get_events.side_effect = processed_pages_data
        if expected_error:
            with pytest.raises(expected_error):
                get_session_events(
                    session_id=mock_metadata["distinct_id"],
                    session_metadata=mock_metadata,
                    team_id=mock_team.id,
                    max_pages=max_pages,
                    items_per_page=items_per_page,
                )
            return
        result_columns, events = get_session_events(
            session_id=mock_metadata["distinct_id"],
            session_metadata=mock_metadata,
            team_id=mock_team.id,
            max_pages=max_pages,
            items_per_page=items_per_page,
        )
        assert len(events) == expected_count
        assert mock_instance.get_events.call_count == expected_iterations
        assert result_columns == mock_columns
        # Verify pagination parameters were passed correctly
        for i, call in enumerate(mock_instance.get_events.call_args_list):
            assert call.kwargs["limit"] == items_per_page
            assert call.kwargs["page"] == i


@pytest.mark.parametrize(
    "exception_data,expected_skip",
    [
        # Should keep exception with many traces (5+)
        (
            {
                "$exception_fingerprint_record": [
                    {"type": "exception", "id": "1", "pieces": ["Error"]},
                    {"type": "frame", "id": "2", "pieces": ["func1", "file1"]},
                    {"type": "frame", "id": "3", "pieces": ["func2", "file2"]},
                    {"type": "frame", "id": "4", "pieces": ["func3", "file3"]},
                    {"type": "frame", "id": "5", "pieces": ["func4", "file4"]},
                    {"type": "frame", "id": "6", "pieces": ["func5", "file5"]},
                ],
                "$exception_types": ["Error"],
                "$exception_values": ["Something went wrong"],
                "$exception_sources": ["file1.ts"],
                "$exception_functions": ["func1"],
            },
            False,
        ),
        # Should keep API-related exception in functions
        (
            {
                "$exception_fingerprint_record": [{"type": "exception", "id": "1", "pieces": ["Error"]}],
                "$exception_types": ["Error"],
                "$exception_values": ["Something went wrong"],
                "$exception_sources": ["file1.ts"],
                "$exception_functions": ["api.fetchData", "handleResponse"],
            },
            False,
        ),
        # Should keep API-related exception in sources
        (
            {
                "$exception_fingerprint_record": [{"type": "exception", "id": "1", "pieces": ["Error"]}],
                "$exception_types": ["Error"],
                "$exception_values": ["Something went wrong"],
                "$exception_sources": ["api/client.ts", "utils.ts"],
                "$exception_functions": ["func1"],
            },
            False,
        ),
        # Should keep API-related exception in values
        (
            {
                "$exception_fingerprint_record": [{"type": "exception", "id": "1", "pieces": ["Error"]}],
                "$exception_types": ["Error"],
                "$exception_values": ["Failed to fetch API data", "Network error"],
                "$exception_sources": ["file1.ts"],
                "$exception_functions": ["func1"],
            },
            False,
        ),
        # Should skip non-API exception with few traces
        (
            {
                "$exception_fingerprint_record": [
                    {"type": "exception", "id": "1", "pieces": ["Error"]},
                    {"type": "frame", "id": "2", "pieces": ["func1", "file1"]},
                ],
                "$exception_types": ["Error"],
                "$exception_values": ["Something went wrong"],
                "$exception_sources": ["file1.ts"],
                "$exception_functions": ["func1"],
            },
            True,
        ),
        # Should skip empty exception data
        (
            {
                "$exception_fingerprint_record": [],
                "$exception_types": [],
                "$exception_values": [],
                "$exception_sources": [],
                "$exception_functions": [],
            },
            True,
        ),
        # Should skip exception with null/None values
        (
            {
                "$exception_fingerprint_record": None,
                "$exception_types": None,
                "$exception_values": None,
                "$exception_sources": None,
                "$exception_functions": None,
            },
            True,
        ),
        # Should skip exception with no matching patterns in any field
        (
            {
                "$exception_fingerprint_record": [{"type": "exception", "id": "1", "pieces": ["Error"]}],
                "$exception_types": ["Error"],
                "$exception_values": ["Generic error"],
                "$exception_sources": ["src/utils.ts"],
                "$exception_functions": ["processData"],
            },
            True,
        ),
        # Should skip exception with invalid JSON in fields
        (
            {
                "$exception_fingerprint_record": "invalid json",
                "$exception_types": "invalid json",
                "$exception_values": "invalid json",
                "$exception_sources": "invalid json",
                "$exception_functions": "invalid json",
            },
            True,
        ),
    ],
)
def test_skip_exception_without_valid_context(exception_data: dict[str, Any], expected_skip: bool):
    # Convert exception data to event row format
    event_row: list[str | datetime | list[str] | None] = [
        None
    ] * 15  # Match the number of columns in mock_event_indexes
    indexes = {
        "$exception_types": 10,
        "$exception_sources": 11,
        "$exception_values": 12,
        "$exception_fingerprint_record": 13,
        "$exception_functions": 14,
    }
    # Set event type to $exception
    event_row[0] = "$exception"
    # Convert exception data to JSON strings
    for key, index in indexes.items():
        event_row[index] = json.dumps(exception_data[key]) if exception_data[key] else None

    assert _skip_exception_without_valid_context(event_row, indexes) is expected_skip
