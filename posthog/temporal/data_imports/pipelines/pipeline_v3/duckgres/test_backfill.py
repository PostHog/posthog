from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill import (
    CHUNK_TARGET_BYTES,
    BackfillChunk,
    _group_files_into_chunks,
    backfill_run_uuid,
)


class TestChunkGrouping:
    def test_groups_small_files_up_to_target(self):
        files = [(f"s3://b/f{i}.parquet", CHUNK_TARGET_BYTES // 4, 10) for i in range(10)]

        chunks = _group_files_into_chunks(files)

        assert [len(c.paths) for c in chunks] == [4, 4, 2]
        assert [c.index for c in chunks] == [0, 1, 2]
        assert sum(c.row_count for c in chunks) == 100

    def test_oversized_file_gets_its_own_chunk(self):
        files = [
            ("s3://b/small.parquet", 100, 1),
            ("s3://b/huge.parquet", CHUNK_TARGET_BYTES * 3, 1000),
            ("s3://b/small2.parquet", 100, 1),
        ]

        chunks = _group_files_into_chunks(files)

        # huge file closes the first chunk and lands alone; trailing small file follows
        assert len(chunks) == 3
        assert chunks[1].paths == ["s3://b/huge.parquet"]

    def test_empty_input(self):
        assert _group_files_into_chunks([]) == []


def test_backfill_run_uuid_is_stable_per_snapshot():
    assert backfill_run_uuid("abc", 7) == "duckgres-backfill-abc-v7"
    assert backfill_run_uuid("abc", 8) != backfill_run_uuid("abc", 7)


def test_chunk_dataclass_shape():
    c = BackfillChunk(0, ["s3://b/f"], 1, 2)
    assert (c.index, c.byte_size, c.row_count) == (0, 1, 2)
