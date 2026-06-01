import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import deltalake
import deltalake.exceptions
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import _WRITER_PROPERTIES, DeltaTableHelper


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


def _make_merge_delta() -> MagicMock:
    delta = MagicMock()
    builder = MagicMock()
    delta.merge.return_value = builder
    builder.when_matched_update_all.return_value = builder
    builder.when_not_matched_insert_all.return_value = builder
    builder.when_matched_update.return_value = builder
    builder.execute.return_value = {"num_target_rows_inserted": 0}
    return delta


class TestWriterPropertiesAndReaderSource:
    """1.2 (tuned WriterProperties on every delta write) + 1.3 (merge source is a streamed RecordBatchReader)."""

    @pytest.mark.asyncio
    async def test_partitioned_merge_uses_reader_and_writer_properties(self):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        helper._is_first_sync = False
        data = pa.table({"id": [1, 2, 3, 4], PARTITION_KEY: ["a", "a", "b", "b"]})
        delta = _make_merge_delta()

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=delta)),
            patch.object(helper, "_evolve_delta_schema", AsyncMock(return_value=delta)),
        ):
            await helper.write_to_deltalake(
                data=data, write_type="incremental", should_overwrite_table=False, primary_keys=["id"]
            )

        assert delta.merge.call_count == 2
        total_rows = 0
        for call in delta.merge.call_args_list:
            assert call.kwargs["streamed_exec"] is True
            assert call.kwargs["writer_properties"] is _WRITER_PROPERTIES
            source = call.kwargs["source"]
            assert isinstance(source, pa.RecordBatchReader)
            total_rows += pa.Table.from_batches(list(source)).num_rows
        assert total_rows == 4

    @pytest.mark.asyncio
    async def test_unpartitioned_merge_uses_reader_and_writer_properties(self):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        helper._is_first_sync = False
        data = pa.table({"id": [1, 2, 3]})
        delta = _make_merge_delta()

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=delta)),
            patch.object(helper, "_evolve_delta_schema", AsyncMock(return_value=delta)),
        ):
            await helper.write_to_deltalake(
                data=data, write_type="incremental", should_overwrite_table=False, primary_keys=["id"]
            )

        assert delta.merge.call_count == 1
        kwargs = delta.merge.call_args.kwargs
        assert kwargs["streamed_exec"] is False
        assert kwargs["writer_properties"] is _WRITER_PROPERTIES
        source = kwargs["source"]
        assert isinstance(source, pa.RecordBatchReader)
        assert pa.Table.from_batches(list(source)).num_rows == 3

    @pytest.mark.asyncio
    async def test_full_refresh_passes_writer_properties_and_keeps_table_on_retry(self):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        data = pa.table({"id": [1, 2, 3]})
        delta = _make_merge_delta()

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=delta)),
            patch.object(helper, "_evolve_delta_schema", AsyncMock(return_value=delta)),
            patch(
                "deltalake.write_deltalake",
                side_effect=[deltalake.exceptions.SchemaMismatchError("mismatch"), None],
            ) as mock_write,
        ):
            await helper.write_to_deltalake(
                data=data, write_type="full_refresh", should_overwrite_table=True, primary_keys=None
            )

        assert mock_write.call_count == 2
        for call in mock_write.call_args_list:
            assert call.kwargs["writer_properties"] is _WRITER_PROPERTIES
            # data must stay a re-iterable Table so the retry isn't handed an exhausted reader.
            assert isinstance(call.kwargs["data"], pa.Table)

    @pytest.mark.asyncio
    async def test_append_passes_writer_properties_with_table_source(self):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        data = pa.table({"id": [1, 2, 3]})
        delta = _make_merge_delta()

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=delta)),
            patch.object(helper, "_evolve_delta_schema", AsyncMock(return_value=delta)),
            patch("deltalake.write_deltalake") as mock_write,
        ):
            await helper.write_to_deltalake(
                data=data, write_type="append", should_overwrite_table=False, primary_keys=None
            )

        assert mock_write.call_args.kwargs["writer_properties"] is _WRITER_PROPERTIES
        assert isinstance(mock_write.call_args.kwargs["data"], pa.Table)

    @pytest.mark.asyncio
    async def test_scd2_close_uses_reader_and_append_passes_writer_properties(self):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        data = pa.table(
            {
                "id": [1, 2],
                "valid_from": [1, 2],
                "valid_to": pa.array([None, None], type=pa.int64()),
            }
        )
        delta = _make_merge_delta()

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=delta)),
            patch.object(helper, "_evolve_delta_schema", AsyncMock(return_value=delta)),
            patch("deltalake.write_deltalake") as mock_write,
        ):
            await helper.write_scd2_to_deltalake(data=data, primary_keys=["id"])

        close_kwargs = delta.merge.call_args.kwargs
        assert close_kwargs["streamed_exec"] is False
        assert close_kwargs["writer_properties"] is _WRITER_PROPERTIES
        assert isinstance(close_kwargs["source"], pa.RecordBatchReader)

        assert mock_write.call_args.kwargs["writer_properties"] is _WRITER_PROPERTIES
        assert isinstance(mock_write.call_args.kwargs["data"], pa.Table)

    def test_writer_properties_values_match_rfc(self):
        assert _WRITER_PROPERTIES.write_batch_size == 8_192
        assert _WRITER_PROPERTIES.max_row_group_size == 131_072
