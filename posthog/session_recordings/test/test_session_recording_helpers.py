import json
import math
import random
import string
from datetime import datetime
from typing import Any, List, Tuple

import pytest
from pytest_mock import MockerFixture

from posthog.session_recordings.session_recording_helpers import (
    RRWEB_MAP_EVENT_TYPE,
    SessionRecordingEventSummary,
    is_active_event,
    preprocess_replay_events_for_blob_ingestion,
    split_replay_events,
)

MILLISECOND_TIMESTAMP = round(datetime(2019, 1, 1).timestamp() * 1000)


def create_activity_data(timestamp: datetime, is_active: bool):
    return SessionRecordingEventSummary(
        timestamp=round(timestamp.timestamp() * 1000),
        type=3,
        data=dict(source=1 if is_active else -1),
    )


def mock_capture_flow(events: List[dict], max_size_bytes=512 * 1024) -> Tuple[List[dict], List[dict]]:
    """
    Returns the legacy events and the new flow ones
    """
    replay_events, other_events = split_replay_events(events)

    new_replay_events = preprocess_replay_events_for_blob_ingestion(replay_events, max_size_bytes=max_size_bytes)

    # TODO this should only be returning the second part of the tuple, it used to return legacy snapshot data too
    return other_events, new_replay_events + other_events


def test_preprocess_with_no_recordings():
    events = [{"event": "$pageview"}, {"event": "$pageleave"}]
    assert mock_capture_flow(events)[0] == events


@pytest.fixture
def raw_snapshot_events():
    return [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 2, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 3, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
    ]


@pytest.fixture
def chunked_and_compressed_snapshot_events():
    chunk_1_events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 4, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 2, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
    ]
    chunk_2_events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 3, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {
                    "type": 3,
                    "timestamp": MILLISECOND_TIMESTAMP,
                    "data": {"source": 2},
                },
                "distinct_id": "abc123",
            },
        },
    ]
    return list(mock_capture_flow(chunk_1_events)[0]) + list(mock_capture_flow(chunk_2_events)[0])


def test_is_active_event():
    timestamp = round(datetime.now().timestamp() * 1000)
    assert is_active_event({"timestamp": timestamp, "type": 3, "data": {}}) is False
    assert is_active_event({"timestamp": timestamp, "type": 2, "data": {"source": 3}}) is False
    assert is_active_event({"timestamp": timestamp, "type": 3, "data": {"source": 3}}) is True


def test_new_ingestion(raw_snapshot_events, mocker: MockerFixture):
    mocker.patch("time.time", return_value=0)

    big_payload = "".join(random.choices(string.ascii_uppercase + string.digits, k=1025))

    events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 3, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 3, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {
                    "type": RRWEB_MAP_EVENT_TYPE.FullSnapshot,
                    "timestamp": 123,
                    "something": big_payload,
                },
                "distinct_id": "abc123",
            },
        },
    ]

    assert list(mock_capture_flow(events, max_size_bytes=2000)[1]) == [
        {
            "event": "$snapshot_items",
            "properties": {
                "distinct_id": "abc123",
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_items": [
                    {"type": 3, "timestamp": 1546300800000},
                    {"type": 3, "timestamp": 1546300800000},
                    {
                        "type": 2,
                        "timestamp": 123,
                        "something": big_payload,
                    },
                ],
            },
        }
    ]


def test_new_ingestion_large_full_snapshot_is_separated(raw_snapshot_events, mocker: MockerFixture):
    mocker.patch("time.time", return_value=0)

    big_payload = "".join(random.choices(string.ascii_uppercase + string.digits, k=10000))

    events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 3, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 3, "timestamp": MILLISECOND_TIMESTAMP},
                "distinct_id": "abc123",
            },
        },
    ] + [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {
                    "type": RRWEB_MAP_EVENT_TYPE.FullSnapshot,
                    "timestamp": 123,
                    "something": big_payload,
                },
                "distinct_id": "abc123",
            },
        },
    ]

    assert list(mock_capture_flow(events, max_size_bytes=2000)[1]) == [
        {
            "event": "$snapshot_items",
            "properties": {
                "distinct_id": "abc123",
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_items": [
                    {
                        "type": 2,
                        "timestamp": 123,
                        "something": big_payload,
                    }
                ],
            },
        },
        {
            "event": "$snapshot_items",
            "properties": {
                "distinct_id": "abc123",
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_items": [
                    {"type": 3, "timestamp": 1546300800000},
                    {"type": 3, "timestamp": 1546300800000},
                ],
            },
        },
    ]


def test_new_ingestion_large_non_full_snapshots_are_separated(raw_snapshot_events, mocker: MockerFixture):
    mocker.patch(
        "posthog.models.utils.UUIDT",
        return_value="0178495e-8521-0000-8e1c-2652fa57099b",
    )
    mocker.patch("time.time", return_value=0)

    almost_too_big_payloads = [
        "".join(random.choices(string.ascii_uppercase + string.digits, k=1024)),
        "".join(random.choices(string.ascii_uppercase + string.digits, k=1024)),
    ]

    events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {
                    "type": 7,
                    "timestamp": 234,
                    "something": almost_too_big_payloads[0],
                },
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {
                    "type": 8,
                    "timestamp": 123,
                    "something": almost_too_big_payloads[1],
                },
                "distinct_id": "abc123",
            },
        },
    ]
    assert list(mock_capture_flow(events, max_size_bytes=2000)[1]) == [
        {
            "event": "$snapshot_items",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_items": [
                    {
                        "type": 7,
                        "timestamp": 234,
                        "something": almost_too_big_payloads[0],
                    }
                ],
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot_items",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_items": [
                    {
                        "type": 8,
                        "timestamp": 123,
                        "something": almost_too_big_payloads[1],
                    }
                ],
                "distinct_id": "abc123",
            },
        },
    ]


def test_new_ingestion_groups_using_snapshot_bytes_if_possible(raw_snapshot_events, mocker: MockerFixture):
    mocker.patch(
        "posthog.models.utils.UUIDT",
        return_value="0178495e-8521-0000-8e1c-2652fa57099b",
    )
    mocker.patch("time.time", return_value=0)

    almost_too_big_event = {
        "type": 7,
        "timestamp": 234,
        "something": "".join(random.choices(string.ascii_uppercase + string.digits, k=1024)),
    }

    small_event = {
        "type": 7,
        "timestamp": 234,
        "something": "small",
    }

    events: List[Any] = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_bytes": len(json.dumps([small_event, small_event])),
                "$snapshot_data": [small_event, small_event],
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_bytes": len(json.dumps([almost_too_big_event])),
                "$snapshot_data": [almost_too_big_event],
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_bytes": len(json.dumps([small_event, small_event, small_event])),
                "$snapshot_data": [small_event, small_event, small_event],
                "distinct_id": "abc123",
            },
        },
    ]

    assert [event["properties"]["$snapshot_bytes"] for event in events] == [
        106,
        1072,
        159,
    ]

    space_with_headroom = math.ceil((106 + 1072 + 50) * 1.05)
    assert list(mock_capture_flow(events, max_size_bytes=space_with_headroom)[1]) == [
        {
            "event": "$snapshot_items",
            "properties": {
                "distinct_id": "abc123",
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_items": [
                    small_event,
                    small_event,
                    almost_too_big_event,
                ],
            },
        },
        {
            "event": "$snapshot_items",
            "properties": {
                "distinct_id": "abc123",
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_items": [small_event, small_event, small_event],
            },
        },
    ]
