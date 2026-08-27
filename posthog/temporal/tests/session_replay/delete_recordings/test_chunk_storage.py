import logging

import pytest
from unittest.mock import MagicMock, patch

from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.session_replay.delete_recordings.object_storage import (
    delete_session_id_chunks,
    generate_chunk_key,
    generate_prefix,
    load_session_id_chunk,
    store_session_id_chunks,
)

STORAGE_MODULE = "posthog.temporal.session_replay.delete_recordings.object_storage.object_storage"


def fake_storage(stored: dict[str, bytes], failed_keys: list[str] | None = None) -> MagicMock:
    # Mirrors the shared client contract: a missing key is only tolerated when the
    # caller opts in, otherwise the read raises.
    def read_bytes(key: str, *, missing_ok: bool = False) -> bytes | None:
        if key in stored:
            return stored[key]
        if not missing_ok:
            raise ObjectStorageError("read failed")
        return None

    storage = MagicMock()
    storage.read_bytes.side_effect = read_bytes
    storage.delete_objects.return_value = failed_keys or []
    return storage


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

    with patch(STORAGE_MODULE) as mock_os:
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


@pytest.mark.parametrize(
    "chunk_content, expected",
    [
        pytest.param(b"session-a\nsession-b\nsession-c", ["session-a", "session-b", "session-c"], id="three_ids"),
        pytest.param(b"session-a\n\nsession-b\n", ["session-a", "session-b"], id="skips_empty_lines"),
    ],
)
@pytest.mark.asyncio
async def test_load_session_id_chunk(chunk_content, expected):
    storage = fake_storage({"deletion-inputs/wf-1/chunk-0002.csv": chunk_content})

    with patch(STORAGE_MODULE, storage):
        result = await load_session_id_chunk("deletion-inputs/wf-1/", 2)

    assert result == expected


@pytest.mark.asyncio
async def test_load_session_id_chunk_raises_when_chunk_is_missing():
    storage = fake_storage({"deletion-inputs/wf-1/chunk-0000.csv": b"session-a"})

    with patch(STORAGE_MODULE, storage):
        with pytest.raises(ValueError, match="deletion-inputs/wf-1/chunk-0001.csv"):
            await load_session_id_chunk("deletion-inputs/wf-1/", 1)


@pytest.mark.parametrize(
    "total_chunks, expected_keys",
    [
        pytest.param(1, ["deletion-inputs/wf-1/chunk-0000.csv"], id="single_chunk"),
        pytest.param(
            3,
            [
                "deletion-inputs/wf-1/chunk-0000.csv",
                "deletion-inputs/wf-1/chunk-0001.csv",
                "deletion-inputs/wf-1/chunk-0002.csv",
            ],
            id="multiple_chunks",
        ),
    ],
)
@pytest.mark.asyncio
async def test_delete_session_id_chunks(total_chunks, expected_keys):
    storage = fake_storage({})

    with patch(STORAGE_MODULE, storage):
        await delete_session_id_chunks("deletion-inputs/wf-1/", total_chunks)

    storage.delete_objects.assert_called_once_with(expected_keys)


@pytest.mark.asyncio
async def test_delete_session_id_chunks_logs_orphans(caplog):
    orphan = "deletion-inputs/wf-1/chunk-0001.csv"
    storage = fake_storage({}, failed_keys=[orphan])

    with (
        patch(STORAGE_MODULE, storage),
        caplog.at_level(logging.WARNING, logger="posthog.temporal.session_replay.delete_recordings.object_storage"),
    ):
        await delete_session_id_chunks("deletion-inputs/wf-1/", 2)

    assert orphan in caplog.text
