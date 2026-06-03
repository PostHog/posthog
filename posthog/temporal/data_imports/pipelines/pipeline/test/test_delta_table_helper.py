import json
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.utils import evolve_pyarrow_schema


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
        schema = pa.schema([("id", pa.int64()), ("name", pa.string())])
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
