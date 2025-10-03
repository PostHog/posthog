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
from posthog.temporal.data_imports.pipelines.pipeline.utils import append_partition_key_to_table
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.temporal.hogql_query_snapshots.backup import clear_backup_object, create_backup_object, restore_from_backup
from posthog.temporal.hogql_query_snapshots.delta_snapshot import (
    DeltaSnapshot,
    calculate_partition_settings,
    get_partition_settings,
)
from posthog.warehouse.models.credential import get_or_create_datawarehouse_credential
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery, aget_saved_query_by_id
from posthog.warehouse.models.snapshot_job import DataWarehouseSnapshotJob
from posthog.warehouse.models.table import DataWarehouseTable, DataWarehouseTableColumns

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateSnapshotJobInputs:
    team_id: int
    saved_query_id: str


async def get_saved_query_or_raise(saved_query_id: str, team_id: int) -> DataWarehouseSavedQuery:
    saved_query = await aget_saved_query_by_id(saved_query_id=saved_query_id, team_id=team_id)
    if saved_query is None:
        raise Exception(f"Saved query: {saved_query_id} cannot be found")
    return saved_query


@temporalio.activity.defn
async def create_snapshot_job_activity(inputs: CreateSnapshotJobInputs) -> tuple[str, bool]:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug(f"Creating DataWarehouseSnapshotJob for {inputs.saved_query_id}")
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    workflow_id = temporalio.activity.info().workflow_id
    workflow_run_id = temporalio.activity.info().workflow_run_id
    saved_query = await get_saved_query_or_raise(inputs.saved_query_id, inputs.team_id)

    job = await start_job_snapshot_run(team, workflow_id, workflow_run_id, saved_query)

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
    saved_query = await get_saved_query_or_raise(inputs.saved_query_id, inputs.team_id)
    create_backup_object(saved_query)


async def start_job_snapshot_run(
    team: Team, workflow_id: str, workflow_run_id: str, saved_query: DataWarehouseSavedQuery
) -> DataWarehouseSnapshotJob:
    job_create = database_sync_to_async(DataWarehouseSnapshotJob.objects.create)
    return await job_create(
        team=team,
        config=saved_query.datawarehousesnapshotconfig,
        status=DataWarehouseSnapshotJob.Status.RUNNING,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
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
    saved_query = await get_saved_query_or_raise(inputs.saved_query_id, inputs.team_id)
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


async def create_snapshot_saved_query(
    inputs: FinishSnapshotJobInputs, job: DataWarehouseSnapshotJob
) -> DataWarehouseSavedQuery:
    assert inputs.snapshot_table_id is not None
    assert inputs.snapshot_ts is not None

    snapshot_table = await database_sync_to_async(DataWarehouseTable.objects.get)(id=inputs.snapshot_table_id)
    formatted_ts = format_snapshot_name(inputs.snapshot_ts)

    saved_query = DataWarehouseSavedQuery(
        team_id=inputs.team_id,
        created_by_id=job.created_by_id,
        name=f"{snapshot_table.name}_{formatted_ts}",
        query={
            "kind": "HogQLQuery",
            "query": f"""SELECT * FROM snapshots.{snapshot_table.name} WHERE _ph_snapshot_ts <= toDateTime('{inputs.snapshot_ts}', 'UTC') AND (_ph_valid_until > toDateTime('{inputs.snapshot_ts}', 'UTC') OR _ph_valid_until IS NULL)""",
        },
        type=DataWarehouseSavedQuery.Type.SNAPSHOT,
        snapshot_table_id=inputs.snapshot_table_id,
    )

    saved_query.columns = await database_sync_to_async(saved_query.get_columns)()
    await database_sync_to_async(saved_query.save)()
    return saved_query


@temporalio.activity.defn
async def finish_snapshot_job_activity(inputs: FinishSnapshotJobInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.adebug(f"Finishing DataWarehouseSnapshotJob for {inputs.job_id}")
    job = await database_sync_to_async(DataWarehouseSnapshotJob.objects.get)(id=inputs.job_id)
    workflow_saved_query = await get_saved_query_or_raise(inputs.saved_query_id, inputs.team_id)

    if inputs.snapshot_table_id is not None and inputs.snapshot_ts is not None:
        job.saved_query = await create_snapshot_saved_query(inputs, job)

    job.status = (
        DataWarehouseSnapshotJob.Status.COMPLETED if inputs.error is None else DataWarehouseSnapshotJob.Status.FAILED
    )
    job.error = inputs.error

    clear_backup_object(workflow_saved_query)
    await database_sync_to_async(job.save)()


@dataclasses.dataclass
class RunSnapshotActivityInputs:
    team_id: int
    saved_query_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "saved_query_id": self.saved_query_id,
        }


def get_or_calculate_partition_settings(
    saved_query: DataWarehouseSavedQuery, delta_snapshot: DeltaSnapshot, logger: FilteringBoundLogger
) -> typing.Any:
    if delta_snapshot.get_delta_table() is None:
        partition_settings = calculate_partition_settings(saved_query)
        if partition_settings is None:
            raise Exception("Failed calculating partition settings. Partition settings are required for snapshot")
        logger.debug(f"Calculated partition settings: {partition_settings}")
        return partition_settings

    partition_settings = get_partition_settings(saved_query)
    if partition_settings is None:
        raise Exception("Failed retrieving partition settings. Partition settings are required for snapshot")
    return partition_settings


def build_snapshot_query(hogql_query: str, merge_key: str, hashed_columns: list[str], snapshot_ts: str) -> str:
    stringified_columns = [f"toString({col})" for col in hashed_columns]
    return f"""
        SELECT
            *,
            {merge_key} AS _ph_merge_key,
            toString(cityHash64(concatWithSeparator('_', {', '.join(stringified_columns)}))) AS _ph_row_hash,
            toDateTime('{snapshot_ts}', 'UTC') AS _ph_snapshot_ts
        FROM {hogql_query}
    """


def transform_and_partition_batch(
    batch: pa.Table, ch_types: typing.Any, partition_settings: typing.Any, merge_key: str, logger: FilteringBoundLogger
) -> pa.Table:
    from posthog.temporal.data_modeling.run_workflow import (
        _transform_date_and_datetimes,
        _transform_unsupported_decimals,
    )

    batch = _transform_unsupported_decimals(batch)
    batch = _transform_date_and_datetimes(batch, ch_types)
    batch = batch.append_column(
        DeltaSnapshot.VALID_UNTIL_COLUMN,
        pa.array([None] * batch.num_rows, type=pa.timestamp("us", tz="UTC")),
    )

    if partition_settings is not None:
        result = append_partition_key_to_table(
            batch, partition_settings.partition_count, None, [merge_key], "md5", None, logger
        )
        if result is not None:
            batch, _, _ = result

    return batch


@temporalio.activity.defn
async def run_snapshot_activity(inputs: RunSnapshotActivityInputs) -> tuple[str, str]:
    from posthog.temporal.data_modeling.run_workflow import hogql_table

    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.ainfo(f"Running snapshot for saved query {inputs.saved_query_id}")

    saved_query = await get_saved_query_or_raise(inputs.saved_query_id, inputs.team_id)
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    delta_snapshot = DeltaSnapshot(saved_query)

    merge_key = delta_snapshot.merge_key
    if merge_key is None:
        raise Exception("Merge key is required for snapshot")

    partition_settings = get_or_calculate_partition_settings(saved_query, delta_snapshot, logger)

    if delta_snapshot.get_delta_table() is None:
        saved_query.datawarehousesnapshotconfig.partition_count = partition_settings.partition_count
        await database_sync_to_async(saved_query.datawarehousesnapshotconfig.save)()

    await logger.ainfo(f"Partition settings: {partition_settings}")

    snapshot_now = dt.datetime.now(dt.UTC)
    snapshot_ts = snapshot_now.strftime("%Y-%m-%d %H:%M:%S.%f")

    query = build_snapshot_query(saved_query.name, merge_key, delta_snapshot.columns, snapshot_ts)

    async for res in hogql_table(query, team, logger):
        batch, ch_types = res
        batch = transform_and_partition_batch(batch, ch_types, partition_settings, merge_key, logger)
        delta_snapshot.snapshot(batch, snapshot_now)

    snapshot_table = delta_snapshot.get_delta_table()
    if snapshot_table is None:
        raise Exception("Snapshot table not found after snapshot")

    file_uris = snapshot_table.file_uris()
    await logger.ainfo(f"Preparing S3 files for querying")
    prepare_s3_files_for_querying(saved_query.snapshot_folder_path, saved_query.normalized_name, file_uris)

    snapshot_table_id = await database_sync_to_async(validate_snapshot_schema)(
        inputs.team_id, saved_query, logger, delta_snapshot.schema.to_hogql_types()
    )

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

    async def _execute_snapshot(
        self, inputs: RunWorkflowInputs, snapshot_exists: bool
    ) -> tuple[str | None, str | None]:
        try:
            snapshot_ts, snapshot_table_id = await temporalio.workflow.execute_activity(
                run_snapshot_activity,
                RunSnapshotActivityInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
                start_to_close_timeout=dt.timedelta(hours=1),
                heartbeat_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=1),
                cancellation_type=temporalio.workflow.ActivityCancellationType.TRY_CANCEL,
            )
            return snapshot_ts, snapshot_table_id
        except Exception:
            if snapshot_exists:
                await temporalio.workflow.execute_activity(
                    restore_from_backup_activity,
                    RestoreFromBackupInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            raise

    @temporalio.workflow.run
    async def run(self, inputs: RunWorkflowInputs) -> None:
        job_id, snapshot_exists = await temporalio.workflow.execute_activity(
            create_snapshot_job_activity,
            CreateSnapshotJobInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if snapshot_exists:
            await temporalio.workflow.execute_activity(
                create_backup_snapshot_job_activity,
                CreateBackupSnapshotJobInputs(team_id=inputs.team_id, saved_query_id=inputs.saved_query_id),
                start_to_close_timeout=dt.timedelta(minutes=20),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

        finish_inputs = FinishSnapshotJobInputs(
            team_id=inputs.team_id,
            job_id=job_id,
            saved_query_id=inputs.saved_query_id,
            error=None,
            snapshot_ts=None,
            snapshot_table_id=None,
        )

        try:
            snapshot_ts, snapshot_table_id = await self._execute_snapshot(inputs, snapshot_exists)
            finish_inputs.snapshot_ts = snapshot_ts
            finish_inputs.snapshot_table_id = snapshot_table_id
        except exceptions.ActivityError as e:
            finish_inputs.error = str(e.cause)
            raise
        except Exception as e:
            finish_inputs.error = str(e)
            raise
        finally:
            await temporalio.workflow.execute_activity(
                finish_snapshot_job_activity,
                finish_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )


def get_or_create_snapshot_table(
    team_id: int, saved_query: DataWarehouseSavedQuery, credential: typing.Any, logger: FilteringBoundLogger
) -> DataWarehouseTable:
    existing_tables = DataWarehouseTable.objects.filter(
        team_id=team_id, name=saved_query.normalized_name, deleted=False, type=DataWarehouseTable.Type.SNAPSHOT
    )

    if existing_tables.exists():
        table = existing_tables.first()
        assert table is not None
        logger.debug(f"Found {existing_tables.count()} existing tables - using {table.id}")
        return table

    logger.debug(f"Creating table for schema: {str(saved_query.id)}")
    return DataWarehouseTable.objects.create(
        credential=credential,
        name=saved_query.normalized_name,
        format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        url_pattern=saved_query.snapshot_url_pattern,
        team_id=team_id,
        row_count=0,
        type=DataWarehouseTable.Type.SNAPSHOT,
    )


def build_table_columns(
    table: DataWarehouseTable, table_schema_dict: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, dict[str, str]]:
    raw_db_columns: DataWarehouseTableColumns = table.get_columns()
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
        columns[column_name] = {"clickhouse": db_column_type, "hogql": hogql_type}

    return columns


def validate_snapshot_schema(
    team_id: int,
    saved_query: DataWarehouseSavedQuery,
    logger: FilteringBoundLogger,
    table_schema_dict: dict[str, str],
) -> str:
    credential = get_or_create_datawarehouse_credential(
        team_id=team_id,
        access_key=settings.AIRBYTE_BUCKET_KEY,
        access_secret=settings.AIRBYTE_BUCKET_SECRET,
    )

    try:
        with transaction.atomic():
            table = get_or_create_snapshot_table(team_id, saved_query, credential, logger)
            table.columns = build_table_columns(table, table_schema_dict, logger)
            table.save()
            return str(table.id)
    except ServerException as err:
        if err.code == 636:
            logger.exception(
                f"Data Warehouse: No data for schema snapshot of {saved_query.normalized_name} for saved query {saved_query.pk}",
                exc_info=err,
            )
        else:
            logger.exception(f"Data Warehouse: Unknown ServerException {saved_query.pk}", exc_info=err)
        raise
    except Exception as e:
        logger.exception(f"Data Warehouse: Could not validate schema for saved query {saved_query.pk}", exc_info=e)
        raise
