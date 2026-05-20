import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.session_replay.delete_recordings.object_storage import (
    delete_session_id_chunks,
    generate_chunk_key,
    generate_prefix,
    load_session_id_chunk,
    store_session_id_chunks,
)


@pytest.mark.parametrize(
    "workflow_id, expected",
    [
        pytest.param("wf-123", "deletion-inputs/wf-123/", id="simple"),
        pytest.param("abc-def-ghi", "deletion-inputs/abc-def-ghi/", id="with_hyphens"),
    ],
)
def test_generate_prefix(workflow_id, expected):
    assert generate_prefix(workflow_id) == expected


@pytest.mark.parametrize(
    "prefix, chunk_index, expected",
    [
        pytest.param("deletion-inputs/wf-1/", 0, "deletion-inputs/wf-1/chunk-0000.csv", id="first"),
        pytest.param("deletion-inputs/wf-1/", 5, "deletion-inputs/wf-1/chunk-0005.csv", id="fifth"),
        pytest.param("deletion-inputs/wf-1/", 99, "deletion-inputs/wf-1/chunk-0099.csv", id="large_index"),
    ],
)
def test_generate_chunk_key(prefix, chunk_index, expected):
    assert generate_chunk_key(prefix, chunk_index) == expected


@pytest.mark.parametrize(
    "session_ids, chunk_size, expected_chunks, expected_last_chunk_size",
    [
        pytest.param(["s1", "s2", "s3"], 10, 1, 3, id="single_chunk"),
        pytest.param([f"s{i}" for i in range(10)], 3, 4, 1, id="multiple_chunks_partial_last"),
        pytest.param([f"s{i}" for i in range(9)], 3, 3, 3, id="exact_multiple"),
        pytest.param(["s1"], 100, 1, 1, id="single_id"),
    ],
)
def test_store_session_id_chunks(session_ids, chunk_size, expected_chunks, expected_last_chunk_size):
    written: dict[str, str] = {}

    with patch("posthog.temporal.session_replay.delete_recordings.object_storage.object_storage") as mock_os:
        mock_os.write = lambda key, content: written.update({key: content})

        prefix, total_chunks = store_session_id_chunks("wf-test", session_ids, chunk_size)

    assert total_chunks == expected_chunks
    assert prefix == "deletion-inputs/wf-test/"
    assert len(written) == expected_chunks

    all_ids: list[str] = []
    for i in range(expected_chunks):
        key = generate_chunk_key(prefix, i)
        assert key in written
        chunk_ids = written[key].split("\n")
        all_ids.extend(chunk_ids)

    assert all_ids == session_ids

    last_key = generate_chunk_key(prefix, expected_chunks - 1)
    assert len(written[last_key].split("\n")) == expected_last_chunk_size


@pytest.mark.asyncio
async def test_load_session_id_chunk():
    chunk_content = b"session-a\nsession-b\nsession-c"

    mock_body = AsyncMock()
    mock_body.read = AsyncMock(return_value=chunk_content)

    mock_client = AsyncMock()
    mock_client.get_object = AsyncMock(return_value={"Body": mock_body})

    with patch("posthog.temporal.session_replay.delete_recordings.object_storage._s3_client") as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await load_session_id_chunk("deletion-inputs/wf-1/", 0)

    assert result == ["session-a", "session-b", "session-c"]
    mock_client.get_object.assert_called_once()


@pytest.mark.asyncio
async def test_load_session_id_chunk_skips_empty_lines():
    chunk_content = b"session-a\n\nsession-b\n"

    mock_body = AsyncMock()
    mock_body.read = AsyncMock(return_value=chunk_content)

    mock_client = AsyncMock()
    mock_client.get_object = AsyncMock(return_value={"Body": mock_body})

    with patch("posthog.temporal.session_replay.delete_recordings.object_storage._s3_client") as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await load_session_id_chunk("deletion-inputs/wf-1/", 0)

    assert result == ["session-a", "session-b"]


@pytest.mark.asyncio
async def test_delete_session_id_chunks():
    mock_client = AsyncMock()
    mock_client.delete_object = AsyncMock()

    with (
        patch("posthog.temporal.session_replay.delete_recordings.object_storage._s3_client") as mock_ctx,
        patch("posthog.temporal.session_replay.delete_recordings.object_storage.settings") as mock_settings,
    ):
        mock_settings.OBJECT_STORAGE_BUCKET = "test-bucket"
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

        await delete_session_id_chunks("deletion-inputs/wf-1/", 3)

    assert mock_client.delete_object.call_count == 3
    mock_client.delete_object.assert_any_call(Bucket="test-bucket", Key="deletion-inputs/wf-1/chunk-0000.csv")
    mock_client.delete_object.assert_any_call(Bucket="test-bucket", Key="deletion-inputs/wf-1/chunk-0001.csv")
    mock_client.delete_object.assert_any_call(Bucket="test-bucket", Key="deletion-inputs/wf-1/chunk-0002.csv")
