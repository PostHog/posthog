import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
    _realign_decimal_buffers,
)
from posthog.temporal.data_imports.pipelines.pipeline.utils import evolve_pyarrow_schema


def _decimal_array(values: list, *, precision: int = 10, scale: int = 2, misaligned: bool) -> pa.Array:
    """Build a Decimal128 array. When `misaligned`, its data buffer is 8-byte but NOT
    16-byte aligned — the exact FFI case delta-rs (arrow-rs) aborts the worker on.

    pyarrow's allocator always returns 64-byte-aligned memory, so the only way to
    reproduce the bad case is to over-allocate and slice off 8 bytes, mimicking what
    arrives across the Arrow C Data Interface from polars / external producers.
    """
    aligned = pa.array(values, type=pa.decimal128(precision, scale))
    if not misaligned:
        return aligned

    data_buffer = aligned.buffers()[1]
    assert data_buffer is not None
    padded = pa.allocate_buffer(data_buffer.size + 16)
    memoryview(padded)[8 : 8 + data_buffer.size] = memoryview(data_buffer)
    misaligned_buffer = padded.slice(8, data_buffer.size)
    assert misaligned_buffer.address % 16 == 8
    # The validity buffer is legitimately None here; pyarrow accepts it but the stub types
    # the list as list[Buffer], so cast rather than fight the (over-strict) annotation.
    buffers = cast("list[pa.Buffer]", [None, misaligned_buffer])
    return pa.Array.from_buffers(pa.decimal128(precision, scale), len(values), buffers)


def _table_is_misaligned(table: pa.Table) -> bool:
    return any(
        pa.types.is_decimal(table.field(i).type)
        and any((b := chunk.buffers()[1]) is not None and b.address % 16 for chunk in table.column(i).chunks)
        for i in range(table.num_columns)
    )


def _make_logger():
    logger = MagicMock()
    logger.adebug = AsyncMock()
    logger.ainfo = AsyncMock()
    logger.awarning = AsyncMock()
    logger.aerror = AsyncMock()
    return logger


@pytest.fixture
def helper():
    return DeltaTableHelper(resource_name="test_resource", job=MagicMock(), logger=_make_logger())


_COMMIT_LAYOUT_CASES: list[tuple[str, list[dict], dict, bool]] = [
    # nested dict layout (older delta-rs / fallback form)
    (
        "nested_dict_exact_match",
        [{"userMetadata": {"run_uuid": "abc", "batch_index": "0"}}],
        {"run_uuid": "abc", "batch_index": "0"},
        True,
    ),
    # delta-rs 1.x flat layout: custom_metadata entries inlined onto the commit dict
    (
        "flat_inlined_exact_match",
        [{"operation": "WRITE", "timestamp": 1, "run_uuid": "abc", "batch_index": "0", "version": 1}],
        {"run_uuid": "abc", "batch_index": "0"},
        True,
    ),
    (
        "flat_missing_one_required_key",
        [{"operation": "WRITE", "run_uuid": "abc", "version": 1}],
        {"run_uuid": "abc", "batch_index": "0"},
        False,
    ),
    # nested JSON-string layout (some delta-rs versions serialize userMetadata as JSON)
    (
        "nested_json_string_exact_match",
        [{"userMetadata": json.dumps({"run_uuid": "abc", "batch_index": "0"})}],
        {"run_uuid": "abc", "batch_index": "0"},
        True,
    ),
    # match is a subset of the metadata — should still match
    (
        "match_is_subset",
        [{"userMetadata": {"run_uuid": "abc", "batch_index": "0", "extra": "field"}}],
        {"run_uuid": "abc"},
        True,
    ),
    # multiple commits, none matching
    (
        "no_match_in_history",
        [
            {"userMetadata": {"run_uuid": "other", "batch_index": "9"}},
            {"userMetadata": {"run_uuid": "abc", "batch_index": "1"}},
        ],
        {"run_uuid": "abc", "batch_index": "0"},
        False,
    ),
    # commits without any custom metadata at all
    (
        "no_metadata_on_any_commit",
        [{"operation": "WRITE"}, {}],
        {"run_uuid": "abc"},
        False,
    ),
    # one commit has invalid JSON userMetadata, the next is a valid match — still found
    (
        "invalid_json_string_skipped_then_match",
        [
            {"userMetadata": "not-valid-json{"},
            {"userMetadata": {"run_uuid": "abc"}},
        ],
        {"run_uuid": "abc"},
        True,
    ),
]


class TestHasCommitWithMetadata:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_delta_table(self, helper: DeltaTableHelper):
        with patch.object(helper, "get_delta_table", AsyncMock(return_value=None)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is False

    @parameterized.expand(
        [(name, history, match, expected) for (name, history, match, expected) in _COMMIT_LAYOUT_CASES]
    )
    @pytest.mark.asyncio
    async def test_layout(self, _name: str, history: list[dict], match: dict, expected: bool):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=history)

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata(match) is expected

    @pytest.mark.asyncio
    async def test_scan_limit_passed_to_history(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=[])

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            await helper.has_commit_with_metadata({"k": "v"}, scan_limit=123)

        mock_delta.history.assert_called_once_with(limit=123)


class TestHasBatchBeenCommitted:
    @parameterized.expand(
        [
            ("string_run_uuid_int_batch", "run-123", 5, True),
            ("zero_batch_index", "run-1", 0, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_wraps_has_commit_with_metadata(
        self, _name: str, run_uuid: str, batch_index: int, mocked_return: bool
    ):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        with patch.object(helper, "has_commit_with_metadata", AsyncMock(return_value=mocked_return)) as m:
            result = await helper.has_batch_been_committed(run_uuid, batch_index)

            assert result is mocked_return
            m.assert_called_once_with({"run_uuid": run_uuid, "batch_index": str(batch_index)})


class TestWriteToDeltalakeCommitMetadataPassThrough:
    """Covers that commit_metadata is forwarded to deltalake.write_deltalake as CommitProperties."""

    @parameterized.expand(
        [
            ("no_metadata", None, None),
            ("with_metadata", {"run_uuid": "abc", "batch_index": "2"}, {"run_uuid": "abc", "batch_index": "2"}),
        ]
    )
    @pytest.mark.asyncio
    async def test_full_refresh_passes_commit_properties(
        self,
        _name: str,
        commit_metadata: dict[str, str] | None,
        expected_custom_metadata: dict[str, str] | None,
    ):
        import pyarrow as pa

        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        data = pa.table({"id": [1, 2, 3]})
        mock_delta = MagicMock()
        mock_delta.schema = MagicMock(return_value=MagicMock(to_arrow=MagicMock(return_value=data.schema)))

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)),
            patch.object(helper, "_evolve_delta_schema", AsyncMock(return_value=mock_delta)),
            patch("deltalake.write_deltalake") as mock_write,
        ):
            await helper.write_to_deltalake(
                data=data,
                write_type="full_refresh",
                should_overwrite_table=False,
                primary_keys=None,
                commit_metadata=commit_metadata,
            )

            assert mock_write.called
            _, kwargs = mock_write.call_args
            commit_properties = kwargs["commit_properties"]
            if expected_custom_metadata is None:
                assert commit_properties is None
            else:
                assert isinstance(commit_properties, deltalake.CommitProperties)
                assert commit_properties.custom_metadata == expected_custom_metadata


def _create_legacy_delta_table(path: str, *, partitioned: bool = False) -> deltalake.DeltaTable:
    """Seed a Delta table that mimics what the old dlt pipeline created:
    business columns plus NOT NULL _dlt_id and _dlt_load_id."""
    fields: list[pa.Field] = [
        pa.field("id", pa.int64()),
        pa.field("name", pa.string()),
        pa.field("_dlt_id", pa.string(), nullable=False),
        pa.field("_dlt_load_id", pa.string(), nullable=False),
    ]
    if partitioned:
        fields.append(pa.field(PARTITION_KEY, pa.string()))

    data_dict: dict[str, Any] = {
        "id": pa.array([1, 2]),
        "name": pa.array(["a", "b"]),
        "_dlt_id": pa.array(["id1", "id2"]),
        "_dlt_load_id": pa.array(["load1", "load1"]),
    }
    if partitioned:
        data_dict[PARTITION_KEY] = pa.array(["p0", "p0"])

    table = pa.table(data_dict, schema=pa.schema(fields))
    deltalake.write_deltalake(path, table, partition_by=PARTITION_KEY if partitioned else None)
    return deltalake.DeltaTable(path)


def _v3_batch(*, partitioned: bool = False) -> pa.Table:
    """Build an incoming batch the way pipeline_v3 does: no _dlt_* columns."""
    data_dict: dict[str, Any] = {"id": pa.array([3, 4]), "name": pa.array(["c", "d"])}
    if partitioned:
        data_dict[PARTITION_KEY] = pa.array(["p0", "p0"])
    return pa.table(data_dict)


def _make_local_helper(delta_uri: str) -> DeltaTableHelper:
    """DeltaTableHelper that reads/writes a local filesystem path instead of S3."""
    helper = DeltaTableHelper(resource_name="test", job=MagicMock(), logger=_make_logger())
    patch.object(helper, "_get_delta_table_uri", new=AsyncMock(return_value=delta_uri)).start()
    patch.object(helper, "_get_credentials", new=MagicMock(return_value={})).start()
    helper.get_delta_table.cache_clear()
    return helper


class TestLegacyDltTableReconciliation:
    """Pipeline_v3 must handle dlt-created Delta tables with NOT NULL _dlt_* columns."""

    def test_raw_merge_rejects_missing_non_nullable_columns(self, tmp_path: Path) -> None:
        """Baseline: proves delta-rs rejects merges when non-nullable columns are absent
        from the source batch. This is the root cause of the production failures."""
        delta_path = str(tmp_path / "table")
        _create_legacy_delta_table(delta_path)
        batch = _v3_batch()
        dt = deltalake.DeltaTable(delta_path)

        with pytest.raises(Exception, match="(?i)(invalid data|non-nullable|validation|not found)"):
            dt.merge(
                source=batch,
                source_alias="source",
                target_alias="target",
                predicate="source.id = target.id",
            ).when_matched_update_all().when_not_matched_insert_all().execute()

    @pytest.mark.parametrize("partitioned", [False, True], ids=["flat", "partitioned"])
    @pytest.mark.asyncio
    async def test_incremental_merge_into_legacy_table(self, partitioned: bool, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = _create_legacy_delta_table(delta_path, partitioned=partitioned)

        helper = _make_local_helper(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(partitioned=partitioned), dt.schema())

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 4
        assert set(final.column("id").to_pylist()) == {1, 2, 3, 4}

        new_rows = final.filter(pc.is_in(final.column("id"), value_set=pa.array([3, 4])))
        assert all(v == "" for v in new_rows.column("_dlt_id").to_pylist())
        assert all(v == "" for v in new_rows.column("_dlt_load_id").to_pylist())

    @pytest.mark.asyncio
    async def test_append_to_legacy_table(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = _create_legacy_delta_table(delta_path)

        helper = _make_local_helper(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(), dt.schema())

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="append",
            should_overwrite_table=False,
            primary_keys=None,
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 4
        assert set(final.column("id").to_pylist()) == {1, 2, 3, 4}

    @pytest.mark.asyncio
    async def test_full_refresh_overwrite_on_legacy_table(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = _create_legacy_delta_table(delta_path)

        helper = _make_local_helper(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(), dt.schema())

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="full_refresh",
            should_overwrite_table=True,
            primary_keys=None,
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 2
        assert all(v == "" for v in final.column("_dlt_id").to_pylist())
        assert all(v == "" for v in final.column("_dlt_load_id").to_pylist())

    @pytest.mark.asyncio
    async def test_v3_native_table_still_merges(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        fields: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("name", pa.string())]
        schema = pa.schema(fields)
        deltalake.write_deltalake(delta_path, pa.table({"id": [1, 2], "name": ["a", "b"]}, schema=schema))

        helper = _make_local_helper(delta_path)
        batch = pa.table({"id": [3], "name": ["c"]})

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 3
        assert set(final.column("id").to_pylist()) == {1, 2, 3}


class TestRealignDecimalBuffers:
    """delta-rs aborts the worker on 8-byte-aligned Decimal128 buffers; we realign them
    to pyarrow's 64-byte allocator before any Delta write. See delta-io/delta-rs#3884."""

    def test_misaligned_decimal_is_realigned(self) -> None:
        table = pa.table({"amount": _decimal_array([1, 2, 3, 4], misaligned=True), "id": pa.array([1, 2, 3, 4])})
        assert _table_is_misaligned(table) is True

        result = _realign_decimal_buffers(table)

        assert _table_is_misaligned(result) is False
        # Values and schema are preserved exactly
        assert result.column("amount").to_pylist() == table.column("amount").to_pylist()
        assert result.column("id").to_pylist() == [1, 2, 3, 4]
        assert result.schema == table.schema

    @pytest.mark.parametrize(
        "table",
        [
            pa.table({"amount": _decimal_array([1, 2, 3], misaligned=False), "id": pa.array([1, 2, 3])}),
            pa.table({"id": pa.array([1, 2, 3]), "name": pa.array(["a", "b", "c"])}),
        ],
        ids=["already_aligned_decimal", "no_decimal_columns"],
    )
    def test_unmisaligned_table_is_returned_unchanged(self, table: pa.Table) -> None:
        assert _table_is_misaligned(table) is False

        result = _realign_decimal_buffers(table)

        # No misalignment found → identity return (no needless copy)
        assert result is table

    def test_only_misaligned_columns_are_rebuilt(self) -> None:
        aligned_dec = _decimal_array([10, 20], misaligned=False)
        misaligned_dec = _decimal_array([30, 40], misaligned=True)
        table = pa.table({"good": aligned_dec, "bad": misaligned_dec, "id": pa.array([1, 2])})

        result = _realign_decimal_buffers(table)

        assert _table_is_misaligned(result) is False
        assert result.column("good").to_pylist() == [10, 20]
        assert result.column("bad").to_pylist() == [30, 40]
        # The already-aligned column keeps its original buffer (rebuilt only what was broken)
        good_buffer = result.column("good").chunks[0].buffers()[1]
        orig_buffer = aligned_dec.buffers()[1]
        assert good_buffer is not None and orig_buffer is not None
        assert good_buffer.address == orig_buffer.address

    def test_multi_chunk_misaligned_column(self) -> None:
        chunked = pa.chunked_array(
            [_decimal_array([1, 2], misaligned=True), _decimal_array([3, 4], misaligned=True)],
            type=pa.decimal128(10, 2),
        )
        table = pa.table({"amount": chunked, "id": pa.array([1, 2, 3, 4])})
        assert _table_is_misaligned(table) is True

        result = _realign_decimal_buffers(table)

        assert _table_is_misaligned(result) is False
        assert result.column("amount").to_pylist() == [1, 2, 3, 4]

    def test_empty_decimal_table(self) -> None:
        table = pa.table({"amount": pa.array([], type=pa.decimal128(10, 2)), "id": pa.array([], type=pa.int64())})

        result = _realign_decimal_buffers(table)

        assert result.num_rows == 0
        assert result.schema == table.schema


class TestWriteMisalignedDecimalEndToEnd:
    """Writes a misaligned-decimal batch through the real delta-rs write path. Without the
    realignment guard, delta-rs would abort the process; with it, the write succeeds."""

    @pytest.mark.parametrize(
        "write_type,should_overwrite",
        [("full_refresh", True), ("append", False), ("incremental", False)],
    )
    @pytest.mark.asyncio
    async def test_write_misaligned_decimal_to_local_delta(
        self, write_type: str, should_overwrite: bool, tmp_path: Path
    ) -> None:
        delta_path = str(tmp_path / "table")
        # Seed the table so incremental/append have an existing target to write into.
        deltalake.write_deltalake(
            delta_path,
            pa.table({"id": pa.array([1, 2]), "amount": _decimal_array([5, 6], misaligned=False)}),
        )

        helper = _make_local_helper(delta_path)
        batch = pa.table({"id": pa.array([3, 4]), "amount": _decimal_array([7, 8], misaligned=True)})
        assert _table_is_misaligned(batch) is True

        result = await helper.write_to_deltalake(
            data=batch,
            write_type=write_type,  # type: ignore[arg-type]
            should_overwrite_table=should_overwrite,
            primary_keys=["id"] if write_type == "incremental" else None,
        )

        final = result.to_pyarrow_table()
        amounts = set(final.column("amount").to_pylist())
        if should_overwrite:
            assert set(final.column("id").to_pylist()) == {3, 4}
        else:
            assert {3, 4}.issubset(set(final.column("id").to_pylist()))
            assert {7, 8}.issubset(amounts)

    @pytest.mark.asyncio
    async def test_write_scd2_misaligned_decimal_to_local_delta(self, tmp_path: Path) -> None:
        # write_scd2_to_deltalake carries its own realignment guard; without it the
        # close-existing merge would hand delta-rs a misaligned decimal and abort the worker.
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        ts_type = pa.timestamp("us", tz="UTC")
        # Seed a current (valid_to IS NULL) row for id=1 so the new batch closes it.
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1]),
                    "amount": _decimal_array([5], misaligned=False),
                    "valid_from": pa.array([ts1], type=ts_type),
                    "valid_to": pa.array([None], type=ts_type),
                }
            ),
        )

        helper = _make_local_helper(delta_path)
        batch = pa.table(
            {
                "id": pa.array([1]),
                "amount": _decimal_array([7], misaligned=True),
                "valid_from": pa.array([ts2], type=ts_type),
                "valid_to": pa.array([None], type=ts_type),
            }
        )
        assert _table_is_misaligned(batch) is True

        result = await helper.write_scd2_to_deltalake(data=batch, primary_keys=["id"])

        final = result.to_pyarrow_table()
        # The seeded row is closed (valid_to set) and the new misaligned row is appended.
        assert final.num_rows == 2
        assert set(final.column("amount").to_pylist()) == {5, 7}
        closed = final.filter(pc.equal(final.column("amount"), Decimal("5.00")))
        assert closed.column("valid_to").to_pylist() == [ts2]


class TestResetTableDeleteGating:
    @pytest.mark.parametrize(
        "delete_s3_data,expect_delete",
        [(True, True), (False, False)],
        ids=["delete", "skip"],
    )
    @pytest.mark.asyncio
    async def test_reset_table_only_deletes_s3_when_requested(
        self, helper: DeltaTableHelper, delete_s3_data: bool, expect_delete: bool
    ) -> None:
        helper._is_first_sync = False
        s3 = AsyncMock()
        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=s3)
        s3_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(helper, "_get_delta_table_uri", new=AsyncMock(return_value="s3://bucket/path")),
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper.aget_s3_client",
                return_value=s3_cm,
            ) as mock_client,
        ):
            await helper.reset_table(delete_s3_data=delete_s3_data)

        assert mock_client.called is expect_delete
        assert s3._rm.called is expect_delete
        # always flags a fresh sync so the next write overwrites
        assert helper._is_first_sync is True
