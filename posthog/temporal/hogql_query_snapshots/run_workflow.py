import json
import typing
import datetime as dt
import dataclasses

from django.db import transaction

import pyarrow as pa
import temporalio
from clickhouse_driver.errors import ServerException
from posthoganalytics import capture_exception
from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger
from temporalio import exceptions
from temporalio.common import RetryPolicy

from posthog import settings
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.deltalake_compaction_job import trigger_compaction_snapshot
from posthog.temporal.data_imports.pipelines.pipeline.utils import append_partition_key_to_table
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.temporal.hogql_query_snapshots.backup import clear_backup_object, create_backup_object, restore_from_backup
from posthog.temporal.hogql_query_snapshots.delta_snapshot import DeltaSnapshot, calculate_partition_settings
from posthog.warehouse.models.credential import get_or_create_datawarehouse_credential
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery, aget_saved_query_by_id
from posthog.warehouse.models.snapshot_job import DataWarehouseSnapshotJob
from posthog.warehouse.models.table import DataWarehouseTable, DataWarehouseTableColumns

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateSnapshotJobInputs:
    team_id: int
    saved_query_id: str


@temporalio.activity.defn
async def create_snapshot_job_activity(inputs: CreateSnapshotJobInputs) -> tuple[str, bool]:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug(f"Creating DataWarehouseSnapshotJob for {inputs.saved_query_id}")
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    workflow_id = temporalio.activity.info().workflow_id
    workflow_run_id = temporalio.activity.info().workflow_run_id
    saved_query = await aget_saved_query_by_id(saved_query_id=inputs.saved_query_id, team_id=inputs.team_id)

    if saved_query is None:
        raise Exception(f"Saved query: {inputs.saved_query_id} cannot be found")

    job = await start_job_snapshot_run(team, workflow_id, workflow_run_id, saved_query)

    # get table that's a snapshot table
    snapshot_table = DeltaSnapshot(saved_query).get_delta_table()
    snapshot_exists = snapshot_table is not None

    return str(job.id), snapshot_exists


@dataclasses.dataclass
class CreateBackupSnapshotJobInputs:
    team_id: int
    saved_query_id: str


@temporalio.activity.defn
async def create_backup_snapshot_job_activity(inputs: CreateBackupSnapshotJobInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug(f"Creating backup object for {inputs.saved_query_id} snapshot")
    saved_query = await aget_saved_query_by_id(saved_query_id=inputs.saved_query_id, team_id=inputs.team_id)

    if saved_query is None:
        raise Exception(f"Saved query: {inputs.saved_query_id} cannot be found")

    create_backup_object(saved_query)


async def start_job_snapshot_run(
    team: Team, workflow_id: str, workflow_run_id: str, saved_query: DataWarehouseSavedQuery
) -> DataWarehouseSnapshotJob:
    """Create a DataWarehouseSnapshotJob record in an async-safe way."""
    job_create = database_sync_to_async(DataWarehouseSnapshotJob.objects.create)
    return await job_create(
        team=team,
        config=saved_query.datawarehousesnapshotconfig,
        status=DataWarehouseSnapshotJob.Status.RUNNING,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        created_by_id=saved_query.created_by_id,
    )


@dataclasses.dataclass
class RestoreFromBackupInputs:
    team_id: int
    saved_query_id: str


@temporalio.activity.defn
async def restore_from_backup_activity(inputs: RestoreFromBackupInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug(f"Restoring from backup for {inputs.saved_query_id}")
    saved_query = await aget_saved_query_by_id(saved_query_id=inputs.saved_query_id, team_id=inputs.team_id)

    if saved_query is None:
        raise Exception(f"Saved query: {inputs.saved_query_id} cannot be found")

    restore_from_backup(saved_query)


@dataclasses.dataclass
class FinishSnapshotJobInputs:
    team_id: int
    job_id: str
    saved_query_id: str
    error: str | None
    snapshot_ts: str | None
    snapshot_table_id: str | None


def format_snapshot_name(snapshot_ts: str) -> str:
    return snapshot_ts.replace(" ", "_").replace(":", "_").replace(".", "_").replace("-", "_")


@temporalio.activity.defn
async def finish_snapshot_job_activity(inputs: FinishSnapshotJobInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug(f"Finishing DataWarehouseSnapshotJob for {inputs.job_id}")
    job = await database_sync_to_async(DataWarehouseSnapshotJob.objects.get)(id=inputs.job_id)
    workflow_saved_query = await aget_saved_query_by_id(saved_query_id=inputs.saved_query_id, team_id=inputs.team_id)

    if inputs.snapshot_table_id is not None and inputs.snapshot_ts is not None:
        snapshot_table = await database_sync_to_async(DataWarehouseTable.objects.get)(id=inputs.snapshot_table_id)

        saved_query = DataWarehouseSavedQuery(
            team_id=inputs.team_id,
            created_by_id=job.created_by_id,
            name=f"{snapshot_table.name}_{format_snapshot_name(inputs.snapshot_ts)}",
            query={
                "kind": "HogQLQuery",
                "query": f"""SELECT * FROM snapshots.{snapshot_table.name} WHERE _ph_snapshot_ts <= toDateTime('{inputs.snapshot_ts}', 'UTC') AND (_ph_valid_until > toDateTime('{inputs.snapshot_ts}', 'UTC') OR _ph_valid_until IS NULL)""",
            },
            type=DataWarehouseSavedQuery.Type.SNAPSHOT,
            snapshot_table_id=inputs.snapshot_table_id,
        )

        saved_query.columns = await database_sync_to_async(saved_query.get_columns)()
        await database_sync_to_async(saved_query.save)()
        job.table = saved_query

    job.status = (
        DataWarehouseSnapshotJob.Status.COMPLETED if inputs.error is None else DataWarehouseSnapshotJob.Status.FAILED
    )
    job.error = inputs.error

    if workflow_saved_query is None:
        raise Exception(f"Saved query: {inputs.saved_query_id} cannot be found")

    clear_backup_object(workflow_saved_query)
    await database_sync_to_async(job.save)()


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
async def run_snapshot_activity(inputs: RunSnapshotActivityInputs) -> tuple[str, str]:
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

    if saved_query is None:
        raise Exception(f"Saved query: {inputs.saved_query_id} cannot be found")

    hogql_query = saved_query.query["query"]
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    delta_snapshot = DeltaSnapshot(saved_query)

    stringified_hashed_columns = [f"toString({column})" for column in delta_snapshot.columns]

    partition_settings = calculate_partition_settings(saved_query)

    # TODO: remove this once we have a way to get the partition settings from config
    # if delta_snapshot.get_delta_table() is None:
    #     partition_settings = calculate_partition_settings(saved_query)
    # else:
    #     partition_settings = get_partition_settings(saved_query)

    merge_key = delta_snapshot.merge_key
    if merge_key is None:
        raise Exception("Merge key is required for snapshot")

    snapshot_ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")

    async for res in hogql_table(
        f"""
                SELECT
                    *,
                    {merge_key} AS _ph_merge_key,
                    toString(cityHash64(concatWithSeparator('_', {', '.join(stringified_hashed_columns)}))) AS _ph_row_hash,
                    toDateTime('{snapshot_ts}', 'UTC') AS _ph_snapshot_ts
                FROM ({hogql_query})
            """,
        team,
        logger,
    ):
        batch, ch_types = res
        batch = _transform_unsupported_decimals(batch)
        batch = _transform_date_and_datetimes(batch, ch_types)

        batch = batch.append_column(
            DeltaSnapshot.VALID_UNTIL_COLUMN,
            pa.array([None] * batch.num_rows, type=pa.timestamp("us", tz="UTC")),
        )

        if partition_settings is not None:
            result = append_partition_key_to_table(
                batch,
                partition_settings.partition_count,
                partition_settings.partition_size,
                [merge_key],
                "md5",
                None,
                logger,
            )
            if result is not None:
                batch, _, _ = result

        delta_snapshot.snapshot(batch)

    snapshot_table = delta_snapshot.get_delta_table()

    if snapshot_table is None:
        raise Exception("Snapshot table not found after snapshot")

    file_uris = []
    file_uris = snapshot_table.file_uris()

    prepare_s3_files_for_querying(saved_query.snapshot_folder_path, saved_query.normalized_name, file_uris)

    snapshot_table_id = await database_sync_to_async(validate_snapshot_schema)(
        inputs.team_id,
        saved_query,
        logger,
        delta_snapshot.schema.to_hogql_types(),
    )

    logger.debug("Triggering workflow to compact and vacuum")
    compaction_job_id = trigger_compaction_snapshot(saved_query, logger)
    logger.debug(f"Compaction workflow id: {compaction_job_id}")

    return snapshot_ts, snapshot_table_id


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


@temporalio.workflow.defn(name="hogql-query-snapshots-run")
class RunWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunWorkflowInputs:
        loaded = json.loads(inputs[0])
        return RunWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: RunWorkflowInputs) -> None:
        job_id, snapshot_exists = await temporalio.workflow.execute_activity(
            create_snapshot_job_activity,
            CreateSnapshotJobInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
            ),
        )

        if snapshot_exists:
            await temporalio.workflow.execute_activity(
                create_backup_snapshot_job_activity,
                CreateBackupSnapshotJobInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
                start_to_close_timeout=dt.timedelta(minutes=20),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                ),
            )

        finish_snapshot_job_inputs = FinishSnapshotJobInputs(
            team_id=inputs.team_id,
            job_id=job_id,
            saved_query_id=inputs.saved_query_id,
            error=None,
            snapshot_ts=None,
            snapshot_table_id=None,
        )

        try:
            snapshot_ts, snapshot_table_id = await temporalio.workflow.execute_activity(
                run_snapshot_activity,
                RunSnapshotActivityInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
                start_to_close_timeout=dt.timedelta(hours=1),
                heartbeat_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                ),
                cancellation_type=temporalio.workflow.ActivityCancellationType.TRY_CANCEL,
            )
            finish_snapshot_job_inputs.snapshot_ts = snapshot_ts
            finish_snapshot_job_inputs.snapshot_table_id = snapshot_table_id
        except exceptions.ActivityError as e:
            finish_snapshot_job_inputs.error = str(e.cause)

            await temporalio.workflow.execute_activity(
                restore_from_backup_activity,
                RestoreFromBackupInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                ),
            )
            raise
        except Exception as e:
            finish_snapshot_job_inputs.error = str(e)

            await temporalio.workflow.execute_activity(
                restore_from_backup_activity,
                RestoreFromBackupInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                ),
            )
            raise
        finally:
            await temporalio.workflow.execute_activity(
                finish_snapshot_job_activity,
                finish_snapshot_job_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                ),
            )


def validate_snapshot_schema(
    team_id: int,
    saved_query: DataWarehouseSavedQuery,
    logger: FilteringBoundLogger,
    table_schema_dict: dict[str, str],
) -> str:
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
                "name": saved_query.normalized_name,
                "format": DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                "url_pattern": new_url_pattern,
                "team_id": team_id,
                "row_count": 0,
                "type": DataWarehouseTable.Type.SNAPSHOT,
            }

            # Check if we already have an orphaned table that we can repurpose
            existing_tables = DataWarehouseTable.objects.filter(
                team_id=team_id, name=saved_query.normalized_name, deleted=False, type=DataWarehouseTable.Type.SNAPSHOT
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

            raw_db_columns: DataWarehouseTableColumns = table_created.get_columns()
            db_columns = {
                key: column.get("clickhouse", "") if isinstance(column, dict) else column
                for key, column in raw_db_columns.items()
            }

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
                f"Data Warehouse: No data for schema snapshot of {saved_query.normalized_name} for saved query {saved_query.pk}",
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

    if table_created is None:
        raise Exception(f"Could not create table for saved query {saved_query.pk}")

    return str(table_created.id)
