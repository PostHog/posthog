import json
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.temporal.delete_recordings.activities import (
    METADATA_DELETION_KEY,
    _parse_block_listing_response,
    _parse_session_recording_list_response,
    delete_recording_blocks,
    delete_recording_lts_data,
    group_recording_blocks,
    load_recording_blocks,
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
    perform_recording_metadata_deletion,
    schedule_recording_metadata_deletion,
)
from posthog.temporal.delete_recordings.types import (
    DeleteRecordingError,
    DeleteRecordingMetadataInput,
    GroupRecordingError,
    LoadRecordingError,
    Recording,
    RecordingBlockGroup,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
    RecordingWithBlocks,
)


@pytest.mark.asyncio
async def test_load_recordings_with_query_single_page():
    TEST_QUERY = 'events=[{"id":"$pageview","type":"events"}]&date_from=-7d'
    TEST_TEAM_ID = 12345
    EXPECTED_SESSION_IDS = [
        "session-1",
        "session-2",
        "session-3",
    ]

    mock_team = MagicMock()
    mock_team.id = TEST_TEAM_ID
    mock_team.organization = MagicMock()
    mock_team.organization.available_product_features = []

    mock_query_results = MagicMock()
    mock_query_results.results = [{"session_id": sid} for sid in EXPECTED_SESSION_IDS]
    mock_query_results.has_more_recording = False
    mock_query_results.next_cursor = None

    with (
        patch("posthog.temporal.delete_recordings.activities.Team.objects") as mock_team_objects,
        patch("posthog.temporal.delete_recordings.activities.database_sync_to_async") as mock_sync_to_async,
        patch("posthog.temporal.delete_recordings.activities.SessionRecordingListFromQuery") as mock_query_class,
    ):
        mock_team_objects.select_related.return_value.only.return_value.aget = AsyncMock(return_value=mock_team)

        mock_query_instance = MagicMock()
        mock_query_instance.run = MagicMock(return_value=mock_query_results)
        mock_query_class.return_value = mock_query_instance

        mock_sync_to_async.return_value = AsyncMock(return_value=mock_query_results)

        result = await load_recordings_with_query(RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID))

        assert result == EXPECTED_SESSION_IDS
        assert mock_sync_to_async.call_count == 1


@pytest.mark.asyncio
async def test_load_recordings_with_query_multiple_pages():
    TEST_QUERY = 'events=[{"id":"$pageview","type":"events"}]&date_from=-30d'
    TEST_TEAM_ID = 67890
    PAGE_1_SESSION_IDS = ["session-1", "session-2"]
    PAGE_2_SESSION_IDS = ["session-3", "session-4"]
    PAGE_3_SESSION_IDS = ["session-5"]
    ALL_SESSION_IDS = PAGE_1_SESSION_IDS + PAGE_2_SESSION_IDS + PAGE_3_SESSION_IDS

    mock_team = MagicMock()
    mock_team.id = TEST_TEAM_ID
    mock_team.organization = MagicMock()
    mock_team.organization.available_product_features = []

    mock_results_page_1 = MagicMock()
    mock_results_page_1.results = [{"session_id": sid} for sid in PAGE_1_SESSION_IDS]
    mock_results_page_1.has_more_recording = True
    mock_results_page_1.next_cursor = "cursor-1"

    mock_results_page_2 = MagicMock()
    mock_results_page_2.results = [{"session_id": sid} for sid in PAGE_2_SESSION_IDS]
    mock_results_page_2.has_more_recording = True
    mock_results_page_2.next_cursor = "cursor-2"

    mock_results_page_3 = MagicMock()
    mock_results_page_3.results = [{"session_id": sid} for sid in PAGE_3_SESSION_IDS]
    mock_results_page_3.has_more_recording = False
    mock_results_page_3.next_cursor = None

    with (
        patch("posthog.temporal.delete_recordings.activities.Team.objects") as mock_team_objects,
        patch("posthog.temporal.delete_recordings.activities.database_sync_to_async") as mock_sync_to_async,
        patch("posthog.temporal.delete_recordings.activities.SessionRecordingListFromQuery") as mock_query_class,
    ):
        mock_team_objects.select_related.return_value.only.return_value.aget = AsyncMock(return_value=mock_team)

        mock_query_instance = MagicMock()
        mock_query_class.return_value = mock_query_instance

        async def mock_run_side_effect():
            if mock_sync_to_async.call_count == 1:
                return mock_results_page_1
            elif mock_sync_to_async.call_count == 2:
                return mock_results_page_2
            else:
                return mock_results_page_3

        mock_sync_to_async.return_value = mock_run_side_effect

        result = await load_recordings_with_query(RecordingsWithQueryInput(query=TEST_QUERY, team_id=TEST_TEAM_ID))

        assert result == ALL_SESSION_IDS
        assert mock_sync_to_async.call_count == 3


def test_parse_session_recording_list_response_valid():
    raw_response = b'{"data":[{"session_id":"session-1"},{"session_id":"session-2"},{"session_id":"session-3"}]}'
    result = _parse_session_recording_list_response(raw_response)
    assert result == ["session-1", "session-2", "session-3"]


def test_parse_session_recording_list_response_empty_data():
    raw_response = b'{"data":[]}'
    result = _parse_session_recording_list_response(raw_response)
    assert result == []


def test_parse_session_recording_list_response_empty_bytes():
    with pytest.raises(LoadRecordingError, match="Got empty response from ClickHouse."):
        _parse_session_recording_list_response(b"")


def test_parse_session_recording_list_response_invalid_json():
    with pytest.raises(LoadRecordingError, match="Unable to parse JSON response from ClickHouse."):
        _parse_session_recording_list_response(b"not valid json")


def test_parse_session_recording_list_response_malformed_json():
    with pytest.raises(LoadRecordingError, match="Got malformed JSON response from ClickHouse."):
        _parse_session_recording_list_response(b'{"wrong_key":[]}')


def test_parse_session_recording_list_response_missing_session_id():
    with pytest.raises(LoadRecordingError, match="Got malformed JSON response from ClickHouse."):
        _parse_session_recording_list_response(b'{"data":[{"wrong_key":"value"}]}')


@pytest.mark.asyncio
async def test_load_recordings_with_person():
    TEST_DISTINCT_IDS = ["user-1", "user-2", "user-3"]
    TEST_TEAM_ID = 99999
    EXPECTED_SESSION_IDS = ["session-a", "session-b", "session-c", "session-d"]

    mock_response = {"data": [{"session_id": sid} for sid in EXPECTED_SESSION_IDS]}
    raw_response = json.dumps(mock_response).encode()

    mock_client = MagicMock()
    mock_ch_response = MagicMock()
    mock_ch_response.content.read = AsyncMock(return_value=raw_response)
    mock_client.aget_query = MagicMock()
    mock_client.aget_query.return_value.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_client.aget_query.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("posthog.temporal.delete_recordings.activities.get_client") as mock_get_client:
        mock_get_client.return_value = mock_client

        result = await load_recordings_with_person(
            RecordingsWithPersonInput(distinct_ids=TEST_DISTINCT_IDS, team_id=TEST_TEAM_ID)
        )

        assert result == EXPECTED_SESSION_IDS


@pytest.mark.asyncio
async def test_load_recordings_with_team_id():
    TEST_TEAM_ID = 12345
    EXPECTED_SESSION_IDS = ["session-1", "session-2", "session-3", "session-4", "session-5"]

    mock_response = {"data": [{"session_id": sid} for sid in EXPECTED_SESSION_IDS]}
    raw_response = json.dumps(mock_response).encode()

    mock_client = MagicMock()
    mock_ch_response = MagicMock()
    mock_ch_response.content.read = AsyncMock(return_value=raw_response)
    mock_client.aget_query = MagicMock()
    mock_client.aget_query.return_value.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_client.aget_query.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("posthog.temporal.delete_recordings.activities.get_client") as mock_get_client:
        mock_get_client.return_value = mock_client

        result = await load_recordings_with_team_id(RecordingsWithTeamInput(team_id=TEST_TEAM_ID))

        assert result == EXPECTED_SESSION_IDS


@pytest.mark.asyncio
async def test_load_recording_blocks():
    import json

    TEST_SESSION_ID = "test-session-123"
    TEST_TEAM_ID = 54321

    mock_block_listing_response = {
        "data": [
            {
                "start_time": "2025-11-17T10:00:00Z",
                "block_first_timestamps": [1700217600000, 1700218600000],
                "block_last_timestamps": [1700218500000, 1700219500000],
                "block_urls": [
                    "s3://bucket/path1?range=bytes=0-1000",
                    "s3://bucket/path2?range=bytes=0-2000",
                ],
            }
        ]
    }
    raw_response = json.dumps(mock_block_listing_response).encode()

    mock_client = MagicMock()
    mock_ch_response = MagicMock()
    mock_ch_response.content.read = AsyncMock(return_value=raw_response)
    mock_client.aget_query = MagicMock()
    mock_client.aget_query.return_value.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_client.aget_query.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    mock_counter = MagicMock()
    mock_counter.add = MagicMock()

    with (
        patch("posthog.temporal.delete_recordings.activities.get_client") as mock_get_client,
        patch("posthog.temporal.delete_recordings.activities.build_block_list") as mock_build_block_list,
        patch("posthog.temporal.delete_recordings.activities.get_block_loaded_counter") as mock_get_counter,
    ):
        mock_get_client.return_value = mock_client
        mock_get_counter.return_value = mock_counter

        expected_blocks = [
            RecordingBlock(
                start_time=datetime(2025, 11, 17, 10, 0, 0),
                end_time=datetime(2025, 11, 17, 10, 15, 0),
                url="s3://bucket/path1?range=bytes=0-1000",
            ),
            RecordingBlock(
                start_time=datetime(2025, 11, 17, 10, 16, 0),
                end_time=datetime(2025, 11, 17, 10, 31, 0),
                url="s3://bucket/path2?range=bytes=0-2000",
            ),
        ]
        mock_build_block_list.return_value = expected_blocks

        result = await load_recording_blocks(Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID))

        assert result == expected_blocks
        assert len(result) == 2
        mock_counter.add.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_delete_recording_blocks():
    import os
    from tempfile import mkstemp

    TEST_SESSION_ID = "session-to-delete"
    TEST_TEAM_ID = 77777
    TEST_PATH = "session_recordings/90d/test-file"
    TEST_RANGES = [(100, 199), (500, 599)]

    # Create a temporary file to simulate the downloaded object storage file
    _, tmpfile = mkstemp()
    try:
        # Write some test data to the file
        test_data = b"\x01" * 100 + b"\x02" * 100 + b"\x03" * 300 + b"\x04" * 100 + b"\x05" * 400
        with open(tmpfile, "wb") as f:
            f.write(test_data)

        mock_storage = MagicMock()
        mock_storage.download_file = AsyncMock()
        mock_storage.upload_file = AsyncMock()
        mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
        mock_storage.__aexit__ = AsyncMock(return_value=None)

        mock_deleted_counter = MagicMock()
        mock_error_counter = MagicMock()

        with (
            patch(
                "posthog.temporal.delete_recordings.activities.session_recording_v2_object_storage.async_client"
            ) as mock_client,
            patch("posthog.temporal.delete_recordings.activities.mkstemp") as mock_mkstemp,
            patch("posthog.temporal.delete_recordings.activities.os.remove") as mock_remove,
            patch("posthog.temporal.delete_recordings.activities.get_block_deleted_counter") as mock_get_deleted,
            patch("posthog.temporal.delete_recordings.activities.get_block_deleted_error_counter") as mock_get_error,
        ):
            mock_client.return_value = mock_storage
            mock_mkstemp.return_value = (0, tmpfile)
            mock_get_deleted.return_value = mock_deleted_counter
            mock_get_error.return_value = mock_error_counter

            input = RecordingBlockGroup(
                recording=Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
                path=TEST_PATH,
                ranges=TEST_RANGES,
            )

            await delete_recording_blocks(input)

            # Verify download was called
            mock_storage.download_file.assert_called_once_with(TEST_PATH, tmpfile)

            # Verify upload was called
            mock_storage.upload_file.assert_called_once_with(TEST_PATH, tmpfile)

            # Verify file was cleaned up
            mock_remove.assert_called_once_with(tmpfile)

            # Verify metrics were updated
            mock_deleted_counter.add.assert_called_once_with(2)
            mock_error_counter.add.assert_called_once_with(0)

            # Verify the blocks were overwritten with zeros in the temp file
            with open(tmpfile, "rb") as f:
                content = f.read()
                # Bytes 100-199 should be zeros
                assert content[100:200] == b"\x00" * 100
                # Bytes 500-599 should be zeros
                assert content[500:600] == b"\x00" * 100
                # Other bytes should be unchanged
                assert content[0:100] == b"\x01" * 100
                assert content[200:500] == b"\x03" * 300
                assert content[600:1000] == b"\x05" * 400
    finally:
        if os.path.exists(tmpfile):
            os.remove(tmpfile)


@pytest.mark.asyncio
async def test_delete_recording_blocks_download_error():
    from posthog.storage import session_recording_v2_object_storage

    TEST_SESSION_ID = "session-error"
    TEST_TEAM_ID = 88888
    TEST_PATH = "session_recordings/error/test-file"
    TEST_RANGES = [(0, 99)]

    mock_storage = MagicMock()
    mock_storage.download_file = AsyncMock(side_effect=session_recording_v2_object_storage.FileDownloadError("Failed"))
    mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
    mock_storage.__aexit__ = AsyncMock(return_value=None)

    mock_deleted_counter = MagicMock()
    mock_error_counter = MagicMock()

    with (
        patch(
            "posthog.temporal.delete_recordings.activities.session_recording_v2_object_storage.async_client"
        ) as mock_client,
        patch("posthog.temporal.delete_recordings.activities.mkstemp") as mock_mkstemp,
        patch("posthog.temporal.delete_recordings.activities.os.remove") as mock_remove,
        patch("posthog.temporal.delete_recordings.activities.get_block_deleted_counter") as mock_get_deleted,
        patch("posthog.temporal.delete_recordings.activities.get_block_deleted_error_counter") as mock_get_error,
    ):
        mock_client.return_value = mock_storage
        tmpfile = "/tmp/test-temp-file"
        mock_mkstemp.return_value = (0, tmpfile)
        mock_get_deleted.return_value = mock_deleted_counter
        mock_get_error.return_value = mock_error_counter

        input = RecordingBlockGroup(
            recording=Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
            path=TEST_PATH,
            ranges=TEST_RANGES,
        )

        # Should not raise an exception, just log a warning
        await delete_recording_blocks(input)

        # Verify download was attempted
        mock_storage.download_file.assert_called_once()

        # Verify upload was NOT called due to download failure
        mock_storage.upload_file.assert_not_called()

        # Verify cleanup happened
        mock_remove.assert_called_once_with(tmpfile)

        # Verify metrics were updated (0 deleted, 0 errors since we skipped the file)
        mock_deleted_counter.add.assert_called_once_with(0)
        mock_error_counter.add.assert_called_once_with(0)


def test_parse_block_listing_response_valid():
    raw_response = b"""{
        "data": [{
            "start_time": "2025-11-17T10:00:00Z",
            "block_first_timestamps": [1700217600000, 1700218600000],
            "block_last_timestamps": [1700218500000, 1700219500000],
            "block_urls": ["url1", "url2"]
        }]
    }"""

    result = _parse_block_listing_response(raw_response)

    assert len(result) == 1
    assert result[0][0] == "2025-11-17T10:00:00Z"
    assert result[0][1] == [1700217600000, 1700218600000]
    assert result[0][2] == [1700218500000, 1700219500000]
    assert result[0][3] == ["url1", "url2"]


def test_parse_block_listing_response_empty_bytes():
    with pytest.raises(DeleteRecordingError, match="Got empty response from ClickHouse."):
        _parse_block_listing_response(b"")


def test_parse_block_listing_response_invalid_json():
    with pytest.raises(DeleteRecordingError, match="Unable to parse JSON response from ClickHouse."):
        _parse_block_listing_response(b"not valid json")


def test_parse_block_listing_response_malformed_json():
    with pytest.raises(DeleteRecordingError, match="Got malformed JSON response from ClickHouse."):
        _parse_block_listing_response(b'{"wrong_key":[]}')


def test_parse_block_listing_response_no_rows():
    with pytest.raises(DeleteRecordingError, match="No rows in response from ClickHouse."):
        _parse_block_listing_response(b'{"data":[]}')


class MockRedis:
    def __init__(self):
        self.sets: dict[str, set[bytes]] = {}

    async def sadd(self, key: str, *values) -> None:
        if key not in self.sets:
            self.sets[key] = set()
        for v in values:
            self.sets[key].add(v.encode() if isinstance(v, str) else v)

    async def smembers(self, key: str) -> set[bytes]:
        return self.sets.get(key, set())

    async def srem(self, key: str, *values) -> None:
        if key in self.sets:
            for v in values:
                self.sets[key].discard(v)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_schedule_recording_metadata_deletion():
    mock_redis = MockRedis()

    with patch("posthog.temporal.delete_recordings.activities.redis.from_url", return_value=mock_redis):
        await schedule_recording_metadata_deletion(Recording(session_id="session-123", team_id=12345))

    assert mock_redis.sets[METADATA_DELETION_KEY] == {b"session-123"}


@pytest.mark.asyncio
async def test_schedule_recording_metadata_deletion_multiple_sessions():
    mock_redis = MockRedis()

    with patch("posthog.temporal.delete_recordings.activities.redis.from_url", return_value=mock_redis):
        await schedule_recording_metadata_deletion(Recording(session_id="session-1", team_id=111))
        await schedule_recording_metadata_deletion(Recording(session_id="session-2", team_id=222))
        await schedule_recording_metadata_deletion(Recording(session_id="session-3", team_id=333))

    assert mock_redis.sets[METADATA_DELETION_KEY] == {b"session-1", b"session-2", b"session-3"}


@pytest.mark.asyncio
async def test_perform_recording_metadata_deletion_no_sessions():
    mock_redis = MockRedis()

    with patch("posthog.temporal.delete_recordings.activities.redis.from_url", return_value=mock_redis):
        await perform_recording_metadata_deletion(DeleteRecordingMetadataInput(dry_run=False))


@pytest.mark.asyncio
async def test_perform_recording_metadata_deletion_with_sessions():
    mock_redis = MockRedis()
    mock_redis.sets[METADATA_DELETION_KEY] = {b"session-1", b"session-2", b"session-3"}

    mock_client = MagicMock()
    mock_client.execute_query = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    mock_session_recording_qs = MagicMock()
    mock_session_recording_qs.filter.return_value.adelete = AsyncMock(return_value=(2, {}))

    mock_session_recording_viewed_qs = MagicMock()
    mock_session_recording_viewed_qs.filter.return_value.adelete = AsyncMock(return_value=(5, {}))

    with (
        patch("posthog.temporal.delete_recordings.activities.redis.from_url", return_value=mock_redis),
        patch("posthog.temporal.delete_recordings.activities.get_client", return_value=mock_client),
        patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_session_recording_qs),
        patch(
            "posthog.temporal.delete_recordings.activities.SessionRecordingViewed.objects",
            mock_session_recording_viewed_qs,
        ),
    ):
        await perform_recording_metadata_deletion(DeleteRecordingMetadataInput(dry_run=False))

    mock_client.execute_query.assert_called_once()
    call_args = mock_client.execute_query.call_args
    query = call_args.args[0] if call_args.args else call_args.kwargs.get("query")
    query_parameters = call_args.kwargs.get("query_parameters")
    assert "ALTER TABLE sharded_session_replay_events" in query
    assert "DELETE WHERE session_id IN" in query
    assert set(query_parameters["session_ids"]) == {"session-1", "session-2", "session-3"}

    mock_session_recording_qs.filter.assert_called_once()
    filter_call = mock_session_recording_qs.filter.call_args
    assert set(filter_call.kwargs["session_id__in"]) == {"session-1", "session-2", "session-3"}

    mock_session_recording_viewed_qs.filter.assert_called_once()
    viewed_filter_call = mock_session_recording_viewed_qs.filter.call_args
    assert set(viewed_filter_call.kwargs["session_id__in"]) == {"session-1", "session-2", "session-3"}

    assert mock_redis.sets[METADATA_DELETION_KEY] == set()


@pytest.mark.asyncio
async def test_perform_recording_metadata_deletion_clears_redis_after_success():
    mock_redis = MockRedis()
    mock_redis.sets[METADATA_DELETION_KEY] = {b"session-a", b"session-b"}

    mock_client = MagicMock()
    mock_client.execute_query = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    mock_session_recording_qs = MagicMock()
    mock_session_recording_qs.filter.return_value.adelete = AsyncMock(return_value=(0, {}))

    mock_session_recording_viewed_qs = MagicMock()
    mock_session_recording_viewed_qs.filter.return_value.adelete = AsyncMock(return_value=(0, {}))

    with (
        patch("posthog.temporal.delete_recordings.activities.redis.from_url", return_value=mock_redis),
        patch("posthog.temporal.delete_recordings.activities.get_client", return_value=mock_client),
        patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_session_recording_qs),
        patch(
            "posthog.temporal.delete_recordings.activities.SessionRecordingViewed.objects",
            mock_session_recording_viewed_qs,
        ),
    ):
        await perform_recording_metadata_deletion(DeleteRecordingMetadataInput(dry_run=False))

    assert mock_redis.sets[METADATA_DELETION_KEY] == set()


@pytest.mark.asyncio
async def test_perform_recording_metadata_deletion_dry_run():
    mock_redis = MockRedis()
    mock_redis.sets[METADATA_DELETION_KEY] = {b"session-1", b"session-2"}

    mock_client = MagicMock()
    mock_client.execute_query = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    mock_session_recording_qs = MagicMock()
    mock_session_recording_qs.filter.return_value.acount = AsyncMock(return_value=2)

    mock_session_recording_viewed_qs = MagicMock()
    mock_session_recording_viewed_qs.filter.return_value.acount = AsyncMock(return_value=3)

    with (
        patch("posthog.temporal.delete_recordings.activities.redis.from_url", return_value=mock_redis),
        patch("posthog.temporal.delete_recordings.activities.get_client", return_value=mock_client),
        patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_session_recording_qs),
        patch(
            "posthog.temporal.delete_recordings.activities.SessionRecordingViewed.objects",
            mock_session_recording_viewed_qs,
        ),
    ):
        await perform_recording_metadata_deletion(DeleteRecordingMetadataInput(dry_run=True))

    # ClickHouse should not be called in dry_run mode
    mock_client.execute_query.assert_not_called()

    # Postgres should use acount instead of adelete
    mock_session_recording_qs.filter.return_value.acount.assert_called_once()
    mock_session_recording_viewed_qs.filter.return_value.acount.assert_called_once()

    # Redis should not be cleared in dry_run mode
    assert mock_redis.sets[METADATA_DELETION_KEY] == {b"session-1", b"session-2"}


@pytest.mark.asyncio
async def test_delete_recording_lts_data_recording_not_found():
    mock_qs = MagicMock()
    mock_qs.filter.return_value.afirst = AsyncMock(return_value=None)

    with patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_qs):
        await delete_recording_lts_data(Recording(session_id="nonexistent-session", team_id=12345))

    mock_qs.filter.assert_called_once_with(session_id="nonexistent-session", team_id=12345)


@pytest.mark.asyncio
async def test_delete_recording_lts_data_no_lts_path():
    mock_recording = MagicMock()
    mock_recording.full_recording_v2_path = None

    mock_qs = MagicMock()
    mock_qs.filter.return_value.afirst = AsyncMock(return_value=mock_recording)

    with patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_qs):
        await delete_recording_lts_data(Recording(session_id="session-no-lts", team_id=12345))


@pytest.mark.asyncio
async def test_delete_recording_lts_data_empty_lts_path():
    mock_recording = MagicMock()
    mock_recording.full_recording_v2_path = ""

    mock_qs = MagicMock()
    mock_qs.filter.return_value.afirst = AsyncMock(return_value=mock_recording)

    with patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_qs):
        await delete_recording_lts_data(Recording(session_id="session-empty-lts", team_id=12345))


@pytest.mark.asyncio
async def test_delete_recording_lts_data_deletes_file():
    mock_recording = MagicMock()
    mock_recording.full_recording_v2_path = "session_recordings_lts/team_id/123/session_id/abc123/data"

    mock_qs = MagicMock()
    mock_qs.filter.return_value.afirst = AsyncMock(return_value=mock_recording)

    mock_storage = MagicMock()
    mock_storage.delete_file = AsyncMock()
    mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
    mock_storage.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_qs),
        patch(
            "posthog.temporal.delete_recordings.activities.session_recording_v2_object_storage.async_client"
        ) as mock_client,
    ):
        mock_client.return_value = mock_storage

        await delete_recording_lts_data(Recording(session_id="session-with-lts", team_id=123))

    mock_storage.delete_file.assert_called_once_with("session_recordings_lts/team_id/123/session_id/abc123/data")


@pytest.mark.asyncio
async def test_delete_recording_lts_data_handles_delete_error():
    from posthog.storage.session_recording_v2_object_storage import FileDeleteError

    mock_recording = MagicMock()
    mock_recording.full_recording_v2_path = "session_recordings_lts/team_id/456/session_id/def456/data"

    mock_qs = MagicMock()
    mock_qs.filter.return_value.afirst = AsyncMock(return_value=mock_recording)

    mock_storage = MagicMock()
    mock_storage.delete_file = AsyncMock(side_effect=FileDeleteError("File not found"))
    mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
    mock_storage.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("posthog.temporal.delete_recordings.activities.SessionRecording.objects", mock_qs),
        patch(
            "posthog.temporal.delete_recordings.activities.session_recording_v2_object_storage.async_client"
        ) as mock_client,
    ):
        mock_client.return_value = mock_storage

        # Should not raise, just log warning
        await delete_recording_lts_data(Recording(session_id="session-delete-error", team_id=456))

    mock_storage.delete_file.assert_called_once()


@pytest.mark.asyncio
async def test_group_recording_blocks_single_file():
    TEST_SESSION_ID = "test-session-123"
    TEST_TEAM_ID = 12345

    blocks = [
        RecordingBlock(
            start_time=datetime(2025, 1, 1, 10, 0, 0),
            end_time=datetime(2025, 1, 1, 10, 15, 0),
            url="s3://bucket/session_recordings/90d/file1?range=bytes=0-1000",
        ),
        RecordingBlock(
            start_time=datetime(2025, 1, 1, 10, 16, 0),
            end_time=datetime(2025, 1, 1, 10, 30, 0),
            url="s3://bucket/session_recordings/90d/file1?range=bytes=1001-2000",
        ),
    ]

    result = await group_recording_blocks(
        RecordingWithBlocks(
            recording=Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
            blocks=blocks,
        )
    )

    assert len(result) == 1
    assert result[0].path == "session_recordings/90d/file1"
    assert result[0].ranges == [(0, 1000), (1001, 2000)]
    assert result[0].recording.session_id == TEST_SESSION_ID
    assert result[0].recording.team_id == TEST_TEAM_ID


@pytest.mark.asyncio
async def test_group_recording_blocks_multiple_files():
    TEST_SESSION_ID = "test-session-456"
    TEST_TEAM_ID = 67890

    blocks = [
        RecordingBlock(
            start_time=datetime(2025, 1, 1, 10, 0, 0),
            end_time=datetime(2025, 1, 1, 10, 15, 0),
            url="s3://bucket/session_recordings/90d/file1?range=bytes=0-1000",
        ),
        RecordingBlock(
            start_time=datetime(2025, 1, 1, 10, 16, 0),
            end_time=datetime(2025, 1, 1, 10, 30, 0),
            url="s3://bucket/session_recordings/1y/file2?range=bytes=500-1500",
        ),
        RecordingBlock(
            start_time=datetime(2025, 1, 1, 10, 31, 0),
            end_time=datetime(2025, 1, 1, 10, 45, 0),
            url="s3://bucket/session_recordings/90d/file1?range=bytes=2000-3000",
        ),
    ]

    result = await group_recording_blocks(
        RecordingWithBlocks(
            recording=Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
            blocks=blocks,
        )
    )

    assert len(result) == 2

    file1_group = next(g for g in result if g.path == "session_recordings/90d/file1")
    file2_group = next(g for g in result if g.path == "session_recordings/1y/file2")

    assert file1_group.ranges == [(0, 1000), (2000, 3000)]
    assert file2_group.ranges == [(500, 1500)]


@pytest.mark.asyncio
async def test_group_recording_blocks_malformed_url():
    TEST_SESSION_ID = "test-session-error"
    TEST_TEAM_ID = 99999

    blocks = [
        RecordingBlock(
            start_time=datetime(2025, 1, 1, 10, 0, 0),
            end_time=datetime(2025, 1, 1, 10, 15, 0),
            url="s3://bucket/session_recordings/90d/file1?invalid=query",
        ),
    ]

    with pytest.raises(GroupRecordingError, match="Got malformed byte range in block URL"):
        await group_recording_blocks(
            RecordingWithBlocks(
                recording=Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
                blocks=blocks,
            )
        )


@pytest.mark.asyncio
async def test_group_recording_blocks_empty_blocks():
    TEST_SESSION_ID = "test-session-empty"
    TEST_TEAM_ID = 11111

    result = await group_recording_blocks(
        RecordingWithBlocks(
            recording=Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
            blocks=[],
        )
    )

    assert result == []


@pytest.mark.asyncio
async def test_delete_recording_blocks_upload_error():
    from posthog.storage import session_recording_v2_object_storage

    TEST_SESSION_ID = "session-upload-error"
    TEST_TEAM_ID = 77777
    TEST_PATH = "session_recordings/error/test-file"
    TEST_RANGES = [(0, 99)]

    mock_storage = MagicMock()
    mock_storage.download_file = AsyncMock()
    mock_storage.upload_file = AsyncMock(side_effect=session_recording_v2_object_storage.FileUploadError("Failed"))
    mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
    mock_storage.__aexit__ = AsyncMock(return_value=None)

    mock_deleted_counter = MagicMock()
    mock_error_counter = MagicMock()

    with (
        patch(
            "posthog.temporal.delete_recordings.activities.session_recording_v2_object_storage.async_client"
        ) as mock_client,
        patch("posthog.temporal.delete_recordings.activities.mkstemp") as mock_mkstemp,
        patch("posthog.temporal.delete_recordings.activities.os.remove") as mock_remove,
        patch("posthog.temporal.delete_recordings.activities.get_block_deleted_counter") as mock_get_deleted,
        patch("posthog.temporal.delete_recordings.activities.get_block_deleted_error_counter") as mock_get_error,
        patch("posthog.temporal.delete_recordings.activities.overwrite_block"),
        patch("posthog.temporal.delete_recordings.activities.Path") as mock_path,
    ):
        mock_client.return_value = mock_storage
        tmpfile = "/tmp/test-temp-file-upload"
        mock_mkstemp.return_value = (0, tmpfile)
        mock_get_deleted.return_value = mock_deleted_counter
        mock_get_error.return_value = mock_error_counter
        mock_path.return_value.stat.return_value.st_size = 100

        input = RecordingBlockGroup(
            recording=Recording(session_id=TEST_SESSION_ID, team_id=TEST_TEAM_ID),
            path=TEST_PATH,
            ranges=TEST_RANGES,
        )

        # Should not raise an exception, just log a warning
        await delete_recording_blocks(input)

        # Verify download was called
        mock_storage.download_file.assert_called_once()

        # Verify upload was attempted
        mock_storage.upload_file.assert_called_once()

        # Verify cleanup happened
        mock_remove.assert_called_once_with(tmpfile)

        # Verify metrics show the block was counted but overall operation may not complete
        mock_deleted_counter.add.assert_called_once()
        mock_error_counter.add.assert_called_once()
