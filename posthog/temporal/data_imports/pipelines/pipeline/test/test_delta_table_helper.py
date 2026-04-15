import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import deltalake

from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper


def _make_logger():
    logger = MagicMock()
    logger.adebug = AsyncMock()
    logger.ainfo = AsyncMock()
    logger.awarning = AsyncMock()
    logger.aerror = AsyncMock()
    return logger


@pytest.fixture
def helper():
    helper = DeltaTableHelper(resource_name="test_resource", job=MagicMock(), logger=_make_logger())
    return helper


class TestHasCommitWithMetadata:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_delta_table(self, helper: DeltaTableHelper):
        with patch.object(helper, "get_delta_table", AsyncMock(return_value=None)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is False

    @pytest.mark.asyncio
    async def test_returns_true_on_exact_match_with_dict_metadata(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(
            return_value=[
                {"userMetadata": {"run_uuid": "abc", "batch_index": "0"}},
            ]
        )

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is True

    @pytest.mark.asyncio
    async def test_returns_true_on_flat_inlined_custom_metadata(self, helper: DeltaTableHelper):
        """delta-rs 1.x inlines CommitProperties.custom_metadata directly onto the
        top-level commit dict alongside operation/timestamp/etc."""
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(
            return_value=[
                {
                    "operation": "WRITE",
                    "timestamp": 1234567890,
                    "run_uuid": "abc",
                    "batch_index": "0",
                    "version": 1,
                },
            ]
        )

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is True

    @pytest.mark.asyncio
    async def test_returns_false_on_flat_commit_missing_one_key(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(
            return_value=[
                {"operation": "WRITE", "run_uuid": "abc", "version": 1},
            ]
        )

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is False

    @pytest.mark.asyncio
    async def test_returns_true_on_exact_match_with_json_string_metadata(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(
            return_value=[
                {"userMetadata": json.dumps({"run_uuid": "abc", "batch_index": "0"})},
            ]
        )

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is True

    @pytest.mark.asyncio
    async def test_returns_true_when_match_is_subset_of_metadata(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(
            return_value=[
                {"userMetadata": {"run_uuid": "abc", "batch_index": "0", "extra": "field"}},
            ]
        )

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc"}) is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_match_in_history(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(
            return_value=[
                {"userMetadata": {"run_uuid": "other", "batch_index": "9"}},
                {"userMetadata": {"run_uuid": "abc", "batch_index": "1"}},
            ]
        )

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is False

    @pytest.mark.asyncio
    async def test_returns_false_when_metadata_missing_on_all_commits(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=[{"operation": "WRITE"}, {}])

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc"}) is False

    @pytest.mark.asyncio
    async def test_ignores_commits_with_invalid_json_string_metadata(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(
            return_value=[
                {"userMetadata": "not-valid-json{"},
                {"userMetadata": {"run_uuid": "abc"}},
            ]
        )

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc"}) is True

    @pytest.mark.asyncio
    async def test_scan_limit_passed_to_history(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=[])

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            await helper.has_commit_with_metadata({"k": "v"}, scan_limit=123)

        mock_delta.history.assert_called_once_with(limit=123)


class TestHasBatchBeenCommitted:
    @pytest.mark.asyncio
    async def test_wraps_has_commit_with_metadata(self, helper: DeltaTableHelper):
        with patch.object(helper, "has_commit_with_metadata", AsyncMock(return_value=True)) as m:
            result = await helper.has_batch_been_committed("run-123", 5)

            assert result is True
            m.assert_called_once_with({"run_uuid": "run-123", "batch_index": "5"})

    @pytest.mark.asyncio
    async def test_stringifies_int_batch_index(self, helper: DeltaTableHelper):
        """Delta custom_metadata must be dict[str, str], so batch_index gets stringified."""
        with patch.object(helper, "has_commit_with_metadata", AsyncMock(return_value=False)) as m:
            await helper.has_batch_been_committed("run-1", 0)
            m.assert_called_once_with({"run_uuid": "run-1", "batch_index": "0"})


class TestWriteToDeltalakeCommitMetadataPassThrough:
    """Covers that commit_metadata is forwarded to deltalake.write_deltalake as CommitProperties."""

    @pytest.mark.asyncio
    async def test_no_metadata_passes_none_commit_properties(self, helper: DeltaTableHelper):
        import pyarrow as pa

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
            )

            assert mock_write.called
            _, kwargs = mock_write.call_args
            assert kwargs["commit_properties"] is None

    @pytest.mark.asyncio
    async def test_with_metadata_builds_commit_properties(self, helper: DeltaTableHelper):
        import pyarrow as pa

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
                commit_metadata={"run_uuid": "abc", "batch_index": "2"},
            )

            assert mock_write.called
            _, kwargs = mock_write.call_args
            commit_properties = kwargs["commit_properties"]
            assert isinstance(commit_properties, deltalake.CommitProperties)
            assert commit_properties.custom_metadata == {"run_uuid": "abc", "batch_index": "2"}
