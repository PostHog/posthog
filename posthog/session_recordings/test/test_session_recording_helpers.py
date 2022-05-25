from datetime import datetime, timedelta, timezone

import pytest
from pytest_mock import MockerFixture

from posthog.session_recordings.helpers import (
    EventActivityData,
    PaginatedList,
    RecordingSegment,
    SnapshotDataTaggedWithWindowId,
    compress_and_chunk_snapshots,
    decompress_chunked_snapshot_data,
    generate_inactive_segments_for_range,
    get_active_segments_from_event_list,
    is_active_event,
    paginate_list,
    preprocess_session_recording_events,
)


def test_preprocess_with_no_recordings():
    events = [{"event": "$pageview"}, {"event": "$pageleave"}]
    assert preprocess_session_recording_events(events) == events


def test_preprocess_recording_event_creates_chunks_split_by_session_and_window_id():
    events = [
        {
            "event": "$snapshot",
            "properties": {"$session_id": "1234", "$snapshot_data": {"type": 2, "foo": "bar"}, "distinct_id": "abc123"},
        },
        {
            "event": "$snapshot",
            "properties": {"$session_id": "1234", "$snapshot_data": {"type": 1, "foo": "bar"}, "distinct_id": "abc123"},
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "5678",
                "$window_id": "1",
                "$snapshot_data": {"type": 1, "foo": "bar"},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "5678",
                "$window_id": "2",
                "$snapshot_data": {"type": 1, "foo": "bar"},
                "distinct_id": "abc123",
            },
        },
    ]

    preprocessed = preprocess_session_recording_events(events)
    assert preprocessed != events
    assert len(preprocessed) == 3
    expected_session_ids = ["1234", "5678", "5678"]
    expected_window_ids = [None, "1", "2"]
    for index, result in enumerate(preprocessed):
        assert result["event"] == "$snapshot"
        assert result["properties"]["$session_id"] == expected_session_ids[index]
        assert result["properties"].get("$window_id") == expected_window_ids[index]
        assert result["properties"]["distinct_id"] == "abc123"
        assert "chunk_id" in result["properties"]["$snapshot_data"]
        assert result["event"] == "$snapshot"

    # it does not rechunk already chunked events
    assert preprocess_session_recording_events(preprocessed) == preprocessed


def test_compression_and_chunking(raw_snapshot_events, mocker: MockerFixture):
    mocker.patch("posthog.models.utils.UUIDT", return_value="0178495e-8521-0000-8e1c-2652fa57099b")
    mocker.patch("time.time", return_value=0)

    assert list(compress_and_chunk_snapshots(raw_snapshot_events)) == [
        {
            "event": "$snapshot",
            "properties": {
                "$window_id": "1",
                "$session_id": "1234",
                "$snapshot_data": {
                    "chunk_count": 1,
                    "chunk_id": "0178495e-8521-0000-8e1c-2652fa57099b",
                    "chunk_index": 0,
                    "compression": "gzip-base64",
                    "data": "H4sIAAAAAAAC//v/L5qhmkGJoYShkqGAIRXIsmJQYDBi0AGSSgxpDPlACBFTYkhiSGQoAtK1YFlMXcZYdVUB5UuAOkH6YhkAxKw6nnAAAAA=",
                    "has_full_snapshot": True,
                },
                "distinct_id": "abc123",
            },
        }
    ]


def test_decompression_results_in_same_data(raw_snapshot_events):
    assert len(list(compress_and_chunk_snapshots(raw_snapshot_events, 1000))) == 1
    assert compress_decompress_and_extract(raw_snapshot_events, 1000) == [
        raw_snapshot_events[0]["properties"]["$snapshot_data"],
        raw_snapshot_events[1]["properties"]["$snapshot_data"],
    ]
    assert len(list(compress_and_chunk_snapshots(raw_snapshot_events, 100))) == 2
    assert compress_decompress_and_extract(raw_snapshot_events, 100) == [
        raw_snapshot_events[0]["properties"]["$snapshot_data"],
        raw_snapshot_events[1]["properties"]["$snapshot_data"],
    ]


def test_has_full_snapshot_property(raw_snapshot_events):
    compressed = list(compress_and_chunk_snapshots(raw_snapshot_events))
    assert len(compressed) == 1
    assert compressed[0]["properties"]["$snapshot_data"]["has_full_snapshot"]

    raw_snapshot_events[0]["properties"]["$snapshot_data"]["type"] = 0
    compressed = list(compress_and_chunk_snapshots(raw_snapshot_events))
    assert len(compressed) == 1
    assert not compressed[0]["properties"]["$snapshot_data"]["has_full_snapshot"]


def test_decompress_uncompressed_events_returns_unmodified_events(raw_snapshot_events):
    snapshot_data_tagged_with_window_id = []
    raw_snapshot_data = []
    for event in raw_snapshot_events:
        snapshot_data_tagged_with_window_id.append(
            SnapshotDataTaggedWithWindowId(snapshot_data=event["properties"]["$snapshot_data"], window_id="1")
        )
        raw_snapshot_data.append(event["properties"]["$snapshot_data"])

    assert (
        decompress_chunked_snapshot_data(1, "someid", snapshot_data_tagged_with_window_id).snapshot_data_by_window_id[
            "1"
        ]
        == raw_snapshot_data
    )


def test_decompress_ignores_if_not_enough_chunks(raw_snapshot_events):
    raw_snapshot_data = [event["properties"]["$snapshot_data"] for event in raw_snapshot_events]
    snapshot_data_list = [
        event["properties"]["$snapshot_data"] for event in compress_and_chunk_snapshots(raw_snapshot_events, 1000)
    ]
    window_id = "abc123"
    snapshot_list = []
    for snapshot_data in snapshot_data_list:
        snapshot_list.append(SnapshotDataTaggedWithWindowId(window_id=window_id, snapshot_data=snapshot_data))

    snapshot_list.append(
        SnapshotDataTaggedWithWindowId(
            snapshot_data={
                "chunk_id": "unique_id",
                "chunk_index": 1,
                "chunk_count": 2,
                "data": {},
                "compression": "gzip",
                "has_full_snapshot": False,
            },
            window_id=window_id,
        )
    )

    assert (
        decompress_chunked_snapshot_data(2, "someid", snapshot_list).snapshot_data_by_window_id[window_id]
        == raw_snapshot_data
    )


def test_paginate_decompression(chunked_and_compressed_snapshot_events):

    snapshot_data = [
        SnapshotDataTaggedWithWindowId(
            snapshot_data=event["properties"]["$snapshot_data"], window_id=event["properties"].get("$window_id")
        )
        for event in chunked_and_compressed_snapshot_events
    ]

    # Get the first chunk
    paginated_events = decompress_chunked_snapshot_data(1, "someid", snapshot_data, 1, 0)
    assert paginated_events.has_next is True
    assert paginated_events.snapshot_data_by_window_id[None][0]["type"] == 4
    assert len(paginated_events.snapshot_data_by_window_id[None]) == 2  # 2 events in a chunk

    # Get the second chunk
    paginated_events = decompress_chunked_snapshot_data(1, "someid", snapshot_data, 1, 1)
    assert paginated_events.has_next is False
    assert paginated_events.snapshot_data_by_window_id["1"][0]["type"] == 3
    assert len(paginated_events.snapshot_data_by_window_id["1"]) == 2  # 2 events in a chunk

    # Limit exceeds the length
    paginated_events = decompress_chunked_snapshot_data(1, "someid", snapshot_data, 10, 0)
    assert paginated_events.has_next is False
    assert len(paginated_events.snapshot_data_by_window_id["1"]) == 2
    assert len(paginated_events.snapshot_data_by_window_id[None]) == 2

    # Offset exceeds the length
    paginated_events = decompress_chunked_snapshot_data(1, "someid", snapshot_data, 10, 2)
    assert paginated_events.has_next is False
    assert paginated_events.snapshot_data_by_window_id == {}

    # Non sequential snapshots
    snapshot_data = snapshot_data[-3:] + snapshot_data[0:-3]
    paginated_events = decompress_chunked_snapshot_data(1, "someid", snapshot_data, 10, 0)
    assert paginated_events.has_next is False
    assert len(paginated_events.snapshot_data_by_window_id["1"]) == 2
    assert len(paginated_events.snapshot_data_by_window_id[None]) == 2

    # No limit or offset provided
    paginated_events = decompress_chunked_snapshot_data(1, "someid", snapshot_data)
    assert paginated_events.has_next is False
    assert len(paginated_events.snapshot_data_by_window_id["1"]) == 2
    assert len(paginated_events.snapshot_data_by_window_id[None]) == 2


def test_decompress_empty_list(chunked_and_compressed_snapshot_events):
    paginated_events = decompress_chunked_snapshot_data(1, "someid", [])
    assert paginated_events.has_next is False
    assert paginated_events.snapshot_data_by_window_id == {}


def test_decompress_data_returning_only_activity_info(chunked_and_compressed_snapshot_events):
    snapshot_data = [
        SnapshotDataTaggedWithWindowId(
            snapshot_data=event["properties"]["$snapshot_data"], window_id=event["properties"].get("$window_id")
        )
        for event in chunked_and_compressed_snapshot_events
    ]
    paginated_events = decompress_chunked_snapshot_data(1, "someid", snapshot_data, return_only_activity_data=True)
    assert paginated_events.snapshot_data_by_window_id == {
        None: [
            {"timestamp": "2019-01-01T00:00:00.000Z", "is_active": False},
            {"timestamp": "2019-01-01T00:00:00.000Z", "is_active": False},
        ],
        "1": [
            {"timestamp": "2019-01-01T00:00:00.000Z", "is_active": False},
            {"timestamp": "2019-01-01T00:00:00.000Z", "is_active": True},
        ],
    }


def test_is_active_event():
    assert is_active_event({}) is False
    assert is_active_event({"type": 3}) is False
    assert is_active_event({"type": 2, "data": {"source": 3}}) is False
    assert is_active_event({"type": 3, "data": {"source": 3}}) is True


def test_get_active_segments_from_event_list():
    base_time = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    events = [
        EventActivityData(is_active=False, timestamp=base_time + timedelta(seconds=0)),
        EventActivityData(is_active=True, timestamp=base_time + timedelta(seconds=10)),
        EventActivityData(is_active=True, timestamp=base_time + timedelta(seconds=10)),
        EventActivityData(is_active=True, timestamp=base_time + timedelta(seconds=40)),
        EventActivityData(is_active=False, timestamp=base_time + timedelta(seconds=60)),
        EventActivityData(is_active=False, timestamp=base_time + timedelta(seconds=100)),
        EventActivityData(is_active=True, timestamp=base_time + timedelta(seconds=110)),
        EventActivityData(is_active=False, timestamp=base_time + timedelta(seconds=120)),
        EventActivityData(is_active=True, timestamp=base_time + timedelta(seconds=170)),
        EventActivityData(is_active=True, timestamp=base_time + timedelta(seconds=180)),
        EventActivityData(is_active=False, timestamp=base_time + timedelta(seconds=200)),
    ]
    active_segments = get_active_segments_from_event_list(events, window_id="1", activity_threshold_seconds=60)
    assert active_segments == [
        RecordingSegment(
            start_time=base_time + timedelta(seconds=10),
            end_time=base_time + timedelta(seconds=40),
            window_id="1",
            is_active=True,
        ),
        RecordingSegment(
            start_time=base_time + timedelta(seconds=110),
            end_time=base_time + timedelta(seconds=180),
            window_id="1",
            is_active=True,
        ),
    ]


def test_get_active_segments_from_single_event():
    base_time = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    events = [
        EventActivityData(is_active=True, timestamp=base_time),
    ]
    active_segments = get_active_segments_from_event_list(events, window_id="1", activity_threshold_seconds=60)
    assert active_segments == [
        RecordingSegment(start_time=base_time, end_time=base_time, window_id="1", is_active=True,),
    ]


def test_get_active_segments_from_no_active_events():
    base_time = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    events = [
        EventActivityData(is_active=False, timestamp=base_time),
        EventActivityData(is_active=False, timestamp=base_time + timedelta(seconds=110)),
    ]
    active_segments = get_active_segments_from_event_list(events, window_id="1", activity_threshold_seconds=60)
    assert active_segments == []


def test_generate_inactive_segments_for_range():
    base_time = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    generated_segments = generate_inactive_segments_for_range(
        base_time,
        base_time + timedelta(seconds=60),
        "2",
        {
            "1": {"start_time": base_time - timedelta(seconds=30), "end_time": base_time + timedelta(seconds=40)},
            "2": {"start_time": base_time, "end_time": base_time + timedelta(seconds=20)},
            "3": {"start_time": base_time + timedelta(seconds=35), "end_time": base_time + timedelta(seconds=80)},
        },
    )
    millisecond = timedelta(milliseconds=1)
    assert generated_segments == [
        RecordingSegment(
            start_time=base_time + millisecond,
            end_time=base_time + timedelta(seconds=20),
            window_id="2",
            is_active=False,
        ),
        RecordingSegment(
            start_time=base_time + timedelta(seconds=20) + millisecond,
            end_time=base_time + timedelta(seconds=40),
            window_id="1",
            is_active=False,
        ),
        RecordingSegment(
            start_time=base_time + timedelta(seconds=40) + millisecond,
            end_time=base_time + timedelta(seconds=60) - millisecond,
            window_id="3",
            is_active=False,
        ),
    ]


def test_generate_inactive_segments_for_range_that_cannot_be_filled():
    base_time = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    generated_segments = generate_inactive_segments_for_range(
        base_time,
        base_time + timedelta(seconds=60),
        "2",
        {
            "2": {"start_time": base_time, "end_time": base_time + timedelta(seconds=20)},
            "3": {"start_time": base_time + timedelta(seconds=35), "end_time": base_time + timedelta(seconds=80)},
        },
    )
    millisecond = timedelta(milliseconds=1)
    assert generated_segments == [
        RecordingSegment(
            start_time=base_time + millisecond,
            end_time=base_time + timedelta(seconds=20),
            window_id="2",
            is_active=False,
        ),
        RecordingSegment(
            start_time=base_time + timedelta(seconds=35),
            end_time=base_time + timedelta(seconds=60) - millisecond,
            window_id="3",
            is_active=False,
        ),
    ]


def test_generate_inactive_segments_for_last_segment():
    base_time = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    generated_segments = generate_inactive_segments_for_range(
        base_time,
        base_time + timedelta(seconds=60),
        "2",
        {"2": {"start_time": base_time, "end_time": base_time + timedelta(seconds=70)},},
        is_last_segment=True,
    )
    millisecond = timedelta(milliseconds=1)
    assert generated_segments == [
        RecordingSegment(
            start_time=base_time + millisecond,
            end_time=base_time + timedelta(seconds=60),
            window_id="2",
            is_active=False,
        ),
    ]


def test_paginate_list():
    list = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert paginate_list(list, 5, 0) == PaginatedList(has_next=True, paginated_list=list[:5])
    assert paginate_list(list, 20, 0) == PaginatedList(has_next=False, paginated_list=list)
    assert paginate_list(list, None, 0) == PaginatedList(has_next=False, paginated_list=list)
    assert paginate_list(list, None, 5) == PaginatedList(has_next=False, paginated_list=list[5:])
    assert paginate_list(list, 5, 5) == PaginatedList(has_next=False, paginated_list=list[5:10])
    assert paginate_list(list, 4, 5) == PaginatedList(has_next=True, paginated_list=list[5:9])


@pytest.fixture
def raw_snapshot_events():
    return [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 2, "foo": "bar"},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$window_id": "1",
                "$snapshot_data": {"type": 3, "foo": "zeta"},
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
                "$snapshot_data": {"type": 4, "foo": "bar", "timestamp": "2019-01-01T00:00:00.000Z"},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 2, "foo": "bar", "timestamp": "2019-01-01T00:00:00.000Z"},
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
                "$snapshot_data": {"type": 3, "foo": "bar", "timestamp": "2019-01-01T00:00:00.000Z"},
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
                    "foo": "bar",
                    "timestamp": "2019-01-01T00:00:00.000Z",
                    "data": {"source": 2},
                },
                "distinct_id": "abc123",
            },
        },
    ]
    return list(compress_and_chunk_snapshots(chunk_1_events)) + list(compress_and_chunk_snapshots(chunk_2_events))


def compress_decompress_and_extract(events, chunk_size):
    snapshot_data_list = [
        event["properties"]["$snapshot_data"] for event in compress_and_chunk_snapshots(events, chunk_size)
    ]
    window_id = "abc123"
    snapshot_list = []
    for snapshot_data in snapshot_data_list:
        snapshot_list.append(SnapshotDataTaggedWithWindowId(window_id=window_id, snapshot_data=snapshot_data))

    return decompress_chunked_snapshot_data(2, "someid", snapshot_list).snapshot_data_by_window_id[window_id]
