import pytest
from pytest_mock import MockerFixture

from posthog.helpers.session_recording import (
    compress_and_chunk_snapshots,
    decompress_chunked_snapshot_data,
    paginate_chunk_decompression,
    preprocess_session_recording_events,
)


def test_preprocess_with_no_recordings():
    events = [{"event": "$pageview"}, {"event": "$pageleave"}]
    assert preprocess_session_recording_events(events) == events


def test_preprocess_recording_event_creates_chunks():
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
            "properties": {"$session_id": "5678", "$snapshot_data": {"type": 1, "foo": "bar"}, "distinct_id": "abc123"},
        },
    ]

    preprocessed = preprocess_session_recording_events(events)
    assert preprocessed != events
    assert len(preprocessed) == 2
    for result, expected_session_id in zip(preprocessed, ["1234", "5678"]):
        assert result["event"] == "$snapshot"
        assert result["properties"]["$session_id"] == expected_session_id
        assert result["properties"]["distinct_id"] == "abc123"
        assert "chunk_id" in result["properties"]["$snapshot_data"]
        assert result["event"] == "$snapshot"

    # it does not rechunk already chunked events
    assert preprocess_session_recording_events(preprocessed) == preprocessed


def test_compression_and_chunking(snapshot_events, mocker: MockerFixture):
    mocker.patch("posthog.models.utils.UUIDT", return_value="0178495e-8521-0000-8e1c-2652fa57099b")
    mocker.patch("time.time", return_value=0)

    assert list(compress_and_chunk_snapshots(snapshot_events)) == [
        {
            "event": "$snapshot",
            "properties": {
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


def test_decompression_results_in_same_data(snapshot_events):
    assert len(list(compress_and_chunk_snapshots(snapshot_events, 1000))) == 1
    assert compress_and_decompress(snapshot_events, 1000) == [
        snapshot_events[0]["properties"]["$snapshot_data"],
        snapshot_events[1]["properties"]["$snapshot_data"],
    ]
    assert len(list(compress_and_chunk_snapshots(snapshot_events, 100))) == 2
    assert compress_and_decompress(snapshot_events, 100) == [
        snapshot_events[0]["properties"]["$snapshot_data"],
        snapshot_events[1]["properties"]["$snapshot_data"],
    ]


def test_has_full_snapshot_property(snapshot_events):
    compressed = list(compress_and_chunk_snapshots(snapshot_events))
    assert len(compressed) == 1
    assert compressed[0]["properties"]["$snapshot_data"]["has_full_snapshot"]

    snapshot_events[0]["properties"]["$snapshot_data"]["type"] = 0
    compressed = list(compress_and_chunk_snapshots(snapshot_events))
    assert len(compressed) == 1
    assert not compressed[0]["properties"]["$snapshot_data"]["has_full_snapshot"]


def test_decompress_returns_unmodified_events(snapshot_events):
    snapshot_data = [event["properties"]["$snapshot_data"] for event in snapshot_events]
    assert list(decompress_chunked_snapshot_data(1, "someid", snapshot_data)) == snapshot_data


def test_decompress_ignores_if_not_enough_chunks(snapshot_events):
    snapshot_data = complete_snapshots = [event["properties"]["$snapshot_data"] for event in snapshot_events]
    snapshot_data.append(
        {
            "$session_id": "1234",
            "$snapshot_data": {
                "chunk_id": "unique_id",
                "chunk_index": 1,
                "chunk_count": 2,
                "data": {},
                "compression": "gzip",
                "has_full_snapshot": False,
            },
            "distinct_id": "abc123",
        }
    )

    assert list(decompress_chunked_snapshot_data(1, "someid", snapshot_data)) == complete_snapshots


def test_paginate_decompression():
    chunk_1_events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 4, "foo": "bar"},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 2, "foo": "bar"},
                "distinct_id": "abc123",
            },
        },
    ]
    chunk_2_events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 3, "foo": "bar"},
                "distinct_id": "abc123",
            },
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 3, "foo": "bar"},
                "distinct_id": "abc123",
            },
        },
    ]
    compressed_snapshot_events = list(compress_and_chunk_snapshots(chunk_1_events)) + list(
        compress_and_chunk_snapshots(chunk_2_events)
    )

    snapshot_data = [event["properties"]["$snapshot_data"] for event in compressed_snapshot_events]

    # Get the first chunk
    paginated_events = paginate_chunk_decompression(1, "someid", snapshot_data, 1, 0)
    assert paginated_events.has_next == True
    assert paginated_events.paginated_list[0]["type"] == 4
    assert len(paginated_events.paginated_list) == 2  # 2 events in a chunk

    # Get the first chunk
    paginated_events = paginate_chunk_decompression(1, "someid", snapshot_data, 1, 1)
    assert paginated_events.has_next == False
    assert paginated_events.paginated_list[0]["type"] == 3
    assert len(paginated_events.paginated_list) == 2  # 2 events in a chunk

    # Limit exceeds the length
    paginated_events = paginate_chunk_decompression(1, "someid", snapshot_data, 10, 0)
    assert paginated_events.has_next == False
    assert len(paginated_events.paginated_list) == 4

    # Offset exceeds the length
    paginated_events = paginate_chunk_decompression(1, "someid", snapshot_data, 10, 2)
    assert paginated_events.has_next == False
    assert paginated_events.paginated_list == []

    # Non sequential snapshots
    snapshot_data = snapshot_data[-3:] + snapshot_data[0:-3]
    paginated_events = paginate_chunk_decompression(1, "someid", snapshot_data, 10, 0)
    assert paginated_events.has_next == False
    assert len(paginated_events.paginated_list) == 4


def test_paginate_decompression_leaves_events_untouched(snapshot_events):
    snapshot_data = [event["properties"]["$snapshot_data"] for event in snapshot_events]

    paginated_events = paginate_chunk_decompression(1, "someid", snapshot_data, 1, 0)
    assert paginated_events.has_next == True
    assert paginated_events.paginated_list[0]["type"] == 2


@pytest.fixture
def snapshot_events():
    return [
        {
            "event": "$snapshot",
            "properties": {"$session_id": "1234", "$snapshot_data": {"type": 2, "foo": "bar"}, "distinct_id": "abc123"},
        },
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": "1234",
                "$snapshot_data": {"type": 3, "foo": "zeta"},
                "distinct_id": "abc123",
            },
        },
    ]


def compress_and_decompress(events, chunk_size):
    snapshot_data = [
        event["properties"]["$snapshot_data"] for event in compress_and_chunk_snapshots(events, chunk_size)
    ]
    return list(decompress_chunked_snapshot_data(1, "someid", snapshot_data))
