import json
import typing
import datetime as dt
import dataclasses

from django.db import transaction

import pyarrow as pa
import temporalio
import asyncstdlib
from clickhouse_driver.errors import ServerException
from posthoganalytics import capture_exception
from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger

from posthog import settings
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.temporal.data_snapshots.delta_snapshot import DeltaSnapshot
from posthog.warehouse.models.credential import get_or_create_datawarehouse_credential
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery, aget_saved_query_by_id
from posthog.warehouse.models.table import DataWarehouseTable

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class RunSnapshotActivityInputs:
    """Inputs for `run_snapshot_activity`.

    Attributes:
        team_id: The team ID of the team whom this snapshot belongs in.
        saved_query_id: The saved query ID to run.
    """

    team_id: int
    saved_query_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "saved_query_id": self.saved_query_id,
        }


@temporalio.activity.defn
async def run_snapshot_activity(inputs: RunSnapshotActivityInputs) -> None:
    """A Temporal activity to run a snapshot."""
    from posthog.temporal.data_modeling.run_workflow import (
        _transform_date_and_datetimes,
        _transform_unsupported_decimals,
        hogql_table,
    )

    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    logger.info(f"Running snapshot for saved query {inputs.saved_query_id}")

    saved_query = await aget_saved_query_by_id(inputs.saved_query_id, inputs.team_id)
    hogql_query = saved_query.query["query"]
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    delta_snapshot = DeltaSnapshot(saved_query)

    stringified_hashed_columns = [f"toString({column})" for column in saved_query.snapshot_config.get("fields", [])]

    async for _, res in asyncstdlib.enumerate(
        hogql_table(
            f"""
        SELECT
            *,
            id AS merge_key,
            toString(cityHash64(concatWithSeparator('_', {', '.join(stringified_hashed_columns)}))) AS row_hash,
            now() AS snapshot_ts
        FROM ({hogql_query})
    """,
            team,
            logger,
        )
    ):
        batch, ch_types = res
        batch = _transform_unsupported_decimals(batch)
        batch = _transform_date_and_datetimes(batch, ch_types)

        batch_with_nulls = batch.append_column(
            DeltaSnapshot.VALID_UNTIL_COLUMN,
            pa.array([None] * batch.num_rows, type=pa.timestamp("us", tz="UTC")),
        )
        delta_snapshot.snapshot(batch_with_nulls)
        snapshot_table_uri = delta_snapshot.get_delta_table()
        file_uris = snapshot_table_uri.file_uris()

        prepare_s3_files_for_querying(saved_query.snapshot_folder_path, saved_query.normalized_name, file_uris)

    await database_sync_to_async(validate_snapshot_schema)(
        inputs.team_id,
        saved_query,
        logger,
        delta_snapshot.schema.to_hogql_types(),
    )


@dataclasses.dataclass
class RunWorkflowInputs:
    team_id: int
    saved_query_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "saved_query_id": self.saved_query_id,
        }


@temporalio.workflow.defn(name="data-snapshots-run")
class RunWorkflow(PostHogWorkflow):
    """A Temporal Workflow to run PostHog data snapshots."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RunWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: RunWorkflowInputs) -> None:
        """Run the workflow."""
        await temporalio.workflow.execute_activity(
            run_snapshot_activity,
            RunSnapshotActivityInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
            start_to_close_timeout=dt.timedelta(hours=1),
            heartbeat_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=1,
            ),
            cancellation_type=temporalio.workflow.ActivityCancellationType.TRY_CANCEL,
        )


def validate_snapshot_schema(
    team_id: int,
    saved_query: DataWarehouseSavedQuery,
    logger: FilteringBoundLogger,
    table_schema_dict: typing.Optional[dict[str, str]] = None,
) -> None:
    """

    Validates the schemas of data that has been synced from saved query snapshot.
    If the schemas are valid, it creates or updates the DataWarehouseTable model with the new url pattern and columns.

    Arguments:
        team_id: The id of the team
        saved_query_id: The id of the saved query being snapshot
    """

    credential = get_or_create_datawarehouse_credential(
        team_id=team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )
    new_url_pattern = saved_query.snapshot_url_pattern

    # Check
    try:
        with transaction.atomic():
            table_params = {
                "credential": credential,
                "name": saved_query.snapshot_normalized_name,
                "format": DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                "url_pattern": new_url_pattern,
                "team_id": team_id,
                "row_count": 0,
                "is_snapshot": True,
            }

            # Check if we already have an orphaned table that we can repurpose
            existing_tables = DataWarehouseTable.objects.filter(
                team_id=team_id, name=saved_query.snapshot_normalized_name, deleted=False, is_snapshot=True
            )
            existing_tables_count = existing_tables.count()
            table_created = None
            if existing_tables_count > 0:
                table_created = existing_tables[0]
                logger.debug(
                    f"Found {existing_tables_count} existing tables - skipping creating and using {table_created.id}"
                )

            if not table_created:
                logger.debug(f"Creating table for schema: {str(saved_query.id)}")
                table_created = DataWarehouseTable.objects.create(**table_params)

            assert isinstance(table_created, DataWarehouseTable) and table_created is not None

            raw_db_columns: dict[str, dict[str, str]] = table_created.get_columns()
            db_columns = {key: column.get("clickhouse", "") for key, column in raw_db_columns.items()}

            columns = {}
            for column_name, db_column_type in db_columns.items():
                hogql_type = table_schema_dict.get(column_name)

                if hogql_type is None:
                    capture_exception(Exception(f"HogQL type not found for column: {column_name}"))
                    continue

                columns[column_name] = {
                    "clickhouse": db_column_type,
                    "hogql": hogql_type,
                }
            table_created.columns = columns
            table_created.save()
    except ServerException as err:
        if err.code == 636:
            logger.exception(
                f"Data Warehouse: No data for schema {saved_query.snapshot_normalized_name} for saved query {saved_query.pk}",
                exc_info=err,
            )
        else:
            logger.exception(
                f"Data Warehouse: Unknown ServerException {saved_query.pk}",
                exc_info=err,
            )
    except Exception as e:
        # TODO: handle other exceptions here
        logger.exception(
            f"Data Warehouse: Could not validate schema for saved query {saved_query.pk}",
            exc_info=e,
        )
        raise
