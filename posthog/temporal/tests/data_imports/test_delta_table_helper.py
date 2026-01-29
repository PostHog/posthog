import uuid

import pytest
from unittest import mock

import pyarrow as pa
import deltalake

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper


def create_test_data(with_partition: bool = False) -> pa.Table:
    """Create test PyArrow table with optional partition key."""
    data = {
        "id": ["1", "2", "3"],
        "name": ["Alice", "Bob", "Carol"],
        "value": [100, 200, 300],
    }
    if with_partition:
        data[PARTITION_KEY] = ["2026/01", "2026/01", "2026/02"]
    return pa.table(data)


def create_mock_job():
    """Create a mock ExternalDataJob."""
    job = mock.MagicMock()
    job.folder_path.return_value = f"test_team/test_source/{uuid.uuid4()}"
    return job


def create_mock_logger():
    """Create a mock logger."""
    return mock.MagicMock()


class TestDeltaTableHelperWriteTypes:
    """Test write_to_deltalake behavior for different write types and configurations."""

    @pytest.fixture
    def helper(self):
        """Create a DeltaTableHelper instance with mocked dependencies."""
        job = create_mock_job()
        logger = create_mock_logger()
        helper = DeltaTableHelper("test_resource", job, logger)
        helper._get_credentials = mock.MagicMock(
            return_value={
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
                "endpoint_url": "http://localhost:19000",
                "region_name": "us-east-1",
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }
        )
        return helper

    def test_incremental_without_primary_keys_raises_exception(self, helper):
        """Incremental sync without primary keys should raise an exception."""
        data = create_test_data()

        # Mock existing table (not first sync)
        with mock.patch.object(helper, "get_delta_table") as mock_get_table:
            mock_get_table.return_value = mock.MagicMock(spec=deltalake.DeltaTable)
            helper._is_first_sync = False

            with pytest.raises(Exception, match="Primary key required for incremental syncs"):
                helper.write_to_deltalake(
                    data=data,
                    write_type="incremental",
                    should_overwrite_table=False,
                    primary_keys=None,
                )

    def test_incremental_with_empty_primary_keys_raises_exception(self, helper):
        """Incremental sync with empty primary keys list should raise an exception."""
        data = create_test_data()

        with mock.patch.object(helper, "get_delta_table") as mock_get_table:
            mock_get_table.return_value = mock.MagicMock(spec=deltalake.DeltaTable)
            helper._is_first_sync = False

            with pytest.raises(Exception, match="Primary key required for incremental syncs"):
                helper.write_to_deltalake(
                    data=data,
                    write_type="incremental",
                    should_overwrite_table=False,
                    primary_keys=[],
                )

    def test_incremental_with_primary_keys_calls_merge(self, helper):
        """Incremental sync with primary keys should use MERGE."""
        data = create_test_data()

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)
        mock_merge_builder = mock.MagicMock()
        mock_delta_table.merge.return_value = mock_merge_builder
        mock_merge_builder.when_matched_update_all.return_value = mock_merge_builder
        mock_merge_builder.when_not_matched_insert_all.return_value = mock_merge_builder
        mock_merge_builder.execute.return_value = {"num_target_rows_updated": 1}

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="incremental",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

            mock_delta_table.merge.assert_called_once()

    def test_append_without_primary_keys_calls_raw_append(self, helper):
        """Append sync without primary keys should use raw append (no MERGE)."""
        data = create_test_data()

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
            mock.patch("deltalake.write_deltalake") as mock_write,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="append",
                should_overwrite_table=False,
                primary_keys=None,
            )

            # Should call write_deltalake with mode="append", not merge
            mock_write.assert_called_once()
            call_kwargs = mock_write.call_args.kwargs
            assert call_kwargs["mode"] == "append"
            mock_delta_table.merge.assert_not_called()

    def test_append_with_empty_primary_keys_calls_raw_append(self, helper):
        """Append sync with empty primary keys list should use raw append."""
        data = create_test_data()

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
            mock.patch("deltalake.write_deltalake") as mock_write,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="append",
                should_overwrite_table=False,
                primary_keys=[],
            )

            mock_write.assert_called_once()
            call_kwargs = mock_write.call_args.kwargs
            assert call_kwargs["mode"] == "append"
            mock_delta_table.merge.assert_not_called()

    def test_append_with_primary_keys_calls_merge(self, helper):
        """Append sync with primary keys should use MERGE for deduplication."""
        data = create_test_data()

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)
        mock_merge_builder = mock.MagicMock()
        mock_delta_table.merge.return_value = mock_merge_builder
        mock_merge_builder.when_matched_update_all.return_value = mock_merge_builder
        mock_merge_builder.when_not_matched_insert_all.return_value = mock_merge_builder
        mock_merge_builder.execute.return_value = {"num_target_rows_updated": 1}

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="append",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

            mock_delta_table.merge.assert_called_once()

    def test_append_first_sync_creates_table(self, helper):
        """Append on first sync should create the table."""
        data = create_test_data()
        mock_created_table = mock.MagicMock(spec=deltalake.DeltaTable)

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch("deltalake.DeltaTable.create") as mock_create,
            mock.patch("deltalake.write_deltalake") as mock_write_deltalake,
        ):
            # Return None first (no table), then return created table at end
            mock_get_table.side_effect = [None, mock_created_table]
            helper._is_first_sync = True
            mock_create.return_value = mock_created_table

            helper.write_to_deltalake(
                data=data,
                write_type="append",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

            mock_create.assert_called_once()
            mock_write_deltalake.assert_called_once()

    def test_append_first_sync_with_primary_keys_does_not_merge(self, helper):
        """Append on first sync with primary keys should NOT use MERGE (no data to merge against)."""
        data = create_test_data()
        mock_created_table = mock.MagicMock(spec=deltalake.DeltaTable)

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch("deltalake.DeltaTable.create") as mock_create,
            mock.patch("deltalake.write_deltalake"),
        ):
            # Return None first, then return created table at end
            mock_get_table.side_effect = [None, mock_created_table]
            helper._is_first_sync = True
            mock_create.return_value = mock_created_table

            helper.write_to_deltalake(
                data=data,
                write_type="append",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

            # Should not call merge on first sync
            mock_created_table.merge.assert_not_called()

    def test_incremental_first_sync_creates_table(self, helper):
        """Incremental on first sync should create the table (overwrite mode)."""
        data = create_test_data()
        mock_created_table = mock.MagicMock(spec=deltalake.DeltaTable)

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch("deltalake.DeltaTable.create") as mock_create,
            mock.patch("deltalake.write_deltalake"),
        ):
            # Return None first, then return created table at end
            mock_get_table.side_effect = [None, mock_created_table]
            helper._is_first_sync = True
            mock_create.return_value = mock_created_table

            helper.write_to_deltalake(
                data=data,
                write_type="incremental",
                should_overwrite_table=True,
                primary_keys=["id"],
            )

            mock_create.assert_called_once()

    def test_full_refresh_overwrites_table(self, helper):
        """Full refresh should overwrite the table."""
        data = create_test_data()

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
            mock.patch("deltalake.write_deltalake") as mock_write,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="full_refresh",
                should_overwrite_table=True,
                primary_keys=["id"],
            )

            mock_write.assert_called_once()
            call_kwargs = mock_write.call_args.kwargs
            assert call_kwargs["mode"] == "overwrite"
            mock_delta_table.merge.assert_not_called()


class TestDeltaTableHelperPartitioning:
    """Test partition-aware MERGE behavior."""

    @pytest.fixture
    def helper(self):
        """Create a DeltaTableHelper instance with mocked dependencies."""
        job = create_mock_job()
        logger = create_mock_logger()
        helper = DeltaTableHelper("test_resource", job, logger)
        helper._get_credentials = mock.MagicMock(
            return_value={
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
                "endpoint_url": "http://localhost:19000",
                "region_name": "us-east-1",
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }
        )
        return helper

    def test_incremental_with_partitioning_merges_per_partition(self, helper):
        """Incremental sync with partitioning should run separate MERGE per partition."""
        data = create_test_data(with_partition=True)

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)
        mock_merge_builder = mock.MagicMock()
        mock_delta_table.merge.return_value = mock_merge_builder
        mock_merge_builder.when_matched_update_all.return_value = mock_merge_builder
        mock_merge_builder.when_not_matched_insert_all.return_value = mock_merge_builder
        mock_merge_builder.execute.return_value = {"num_target_rows_updated": 1}

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="incremental",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

            # Should call merge twice (once per unique partition: 2026/01 and 2026/02)
            assert mock_delta_table.merge.call_count == 2

    def test_append_with_primary_keys_and_partitioning_merges_per_partition(self, helper):
        """Append sync with primary keys and partitioning should run separate MERGE per partition."""
        data = create_test_data(with_partition=True)

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)
        mock_merge_builder = mock.MagicMock()
        mock_delta_table.merge.return_value = mock_merge_builder
        mock_merge_builder.when_matched_update_all.return_value = mock_merge_builder
        mock_merge_builder.when_not_matched_insert_all.return_value = mock_merge_builder
        mock_merge_builder.execute.return_value = {"num_target_rows_updated": 1}

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="append",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

            # Should call merge twice (once per unique partition)
            assert mock_delta_table.merge.call_count == 2

    def test_merge_predicate_includes_partition_key(self, helper):
        """MERGE predicate should include partition key when partitioning is enabled."""
        data = create_test_data(with_partition=True)

        mock_delta_table = mock.MagicMock(spec=deltalake.DeltaTable)
        mock_merge_builder = mock.MagicMock()
        mock_delta_table.merge.return_value = mock_merge_builder
        mock_merge_builder.when_matched_update_all.return_value = mock_merge_builder
        mock_merge_builder.when_not_matched_insert_all.return_value = mock_merge_builder
        mock_merge_builder.execute.return_value = {"num_target_rows_updated": 1}

        with (
            mock.patch.object(helper, "get_delta_table") as mock_get_table,
            mock.patch.object(helper, "_evolve_delta_schema") as mock_evolve,
        ):
            mock_get_table.return_value = mock_delta_table
            mock_evolve.return_value = mock_delta_table
            helper._is_first_sync = False

            helper.write_to_deltalake(
                data=data,
                write_type="incremental",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

            # Check that merge was called with partition key in predicate
            merge_calls = mock_delta_table.merge.call_args_list
            for call in merge_calls:
                predicate = call.kwargs["predicate"]
                assert PARTITION_KEY in predicate
                assert "target." + PARTITION_KEY in predicate
