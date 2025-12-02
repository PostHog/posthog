import json
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.temporal.delete_recordings.activities import (
    _parse_block_listing_response,
    _parse_session_recording_list_response,
    delete_recording_blocks,
    load_recording_blocks,
    load_recordings_with_person,
    load_recordings_with_query,
    load_recordings_with_team_id,
)
from posthog.temporal.delete_recordings.types import (
    DeleteRecordingError,
    LoadRecordingError,
    Recording,
    RecordingBlockGroup,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
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
