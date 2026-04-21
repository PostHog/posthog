import time
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings as django_settings

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE
from posthog.clickhouse.cluster import (
    AlterTableMutationRunner,
    ClickhouseCluster,
    LightweightDeleteMutationRunner,
    Query,
)
from posthog.dags.common import JobOwners
from posthog.dags.deletes import deletes_job
from posthog.models.data_deletion_request import (
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
    jsonhas_expr,
)
from posthog.models.event.sql import EVENTS_DATA_TABLE

from ee.clickhouse.materialized_columns.columns import MaterializedColumnDetails

OWNER_TAG = {"owner": JobOwners.TEAM_CLICKHOUSE.value}


class DataDeletionRequestConfig(dagster.Config):
    request_id: str = pydantic.Field(description="UUID of the DataDeletionRequest to execute.")


@dataclass
class DeletionRequestContext:
    request_id: str
    team_id: int
    start_time: datetime
    end_time: datetime
    events: list[str]
    properties: list[str] = field(default_factory=list)
    execution_mode: str = ExecutionMode.IMMEDIATE.value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _temp_table_name(team_id: int, request_id: str) -> str:
    return f"tmp_dag_team_{team_id}_prop_rm_{request_id[:8]}"


def _property_filter_clause(properties: list[str]) -> str:
    if len(properties) == 1:
        return jsonhas_expr(properties[0], "fp_0")
    exprs = [jsonhas_expr(prop, f"fp_{i}") for i, prop in enumerate(properties)]
    return f"({' OR '.join(exprs)})"


def _property_filter_params(properties: list[str]) -> dict:
    params: dict[str, str] = {}
    for i, prop in enumerate(properties):
        for j, part in enumerate(prop.split(".")):
            params[f"fp_{i}_{j}"] = part
    return params


def _base_params(ctx: DeletionRequestContext) -> dict:
    return {
        "team_id": ctx.team_id,
        "start_time": ctx.start_time,
        "end_time": ctx.end_time,
        "events": ctx.events,
        **_property_filter_params(ctx.properties),
    }


EVENT_REMOVAL_PREDICATE = (
    "team_id = %(team_id)s AND timestamp >= %(start_time)s AND timestamp < %(end_time)s AND event IN %(events)s"
)


def _event_removal_params(request: DataDeletionRequest) -> dict:
    return {
        "team_id": request.team_id,
        "start_time": request.start_time,
        "end_time": request.end_time,
        "events": request.events,
    }


def _get_affected_mat_columns(client: Client, table: str, properties: list[str]) -> list[tuple[str, bool]]:
    """Query a specific shard for DEFAULT materialized columns matching deleted properties.

    Returns ``(column_name, is_nullable)`` for DEFAULT columns whose comment follows
    the ``column_materializer::properties::<prop>`` convention.  Only DEFAULT columns
    are returned because they are included in ``SELECT *`` (so stale values propagate
    on re-insert) and can be reset via ``ALTER TABLE UPDATE``.  MATERIALIZED columns
    are excluded — ClickHouse recomputes them automatically at insert time.
    """
    database = django_settings.CLICKHOUSE_DATABASE
    rows = client.execute(
        """
        SELECT name, comment, type LIKE 'Nullable(%%)'
        FROM system.columns
        WHERE database = %(database)s
          AND table = %(table)s
          AND default_kind = 'DEFAULT'
          AND comment LIKE '%%column_materializer::%%'
          AND comment NOT LIKE '%%column_materializer::elements_chain::%%'
        """,
        {"database": database, "table": table},
    )

    target_props = set(properties)
    result: list[tuple[str, bool]] = []
    for col_name, comment, is_nullable in rows:
        details = MaterializedColumnDetails.from_column_comment(comment)
        if details.table_column == "properties" and details.property_name in target_props:
            result.append((col_name, bool(is_nullable)))
    return result


def _create_local_staging_table(client: Client, source_table: str, staging_table: str) -> None:
    """Create a non-replicated local copy of the source table schema."""
    database = django_settings.CLICKHOUSE_DATABASE

    rows = client.execute(
        "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": staging_table},
    )
    if rows[0][0] > 0:
        return

    rows = client.execute(
        "SELECT engine_full FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": source_table},
    )
    if not rows:
        raise dagster.Failure(description=f"Source table {database}.{source_table} not found")

    client.execute(
        f"CREATE TABLE IF NOT EXISTS {database}.{staging_table} AS {database}.{source_table} ENGINE = MergeTree()"
    )


# ---------------------------------------------------------------------------
# Event removal ops
# ---------------------------------------------------------------------------


@dagster.op(tags=OWNER_TAG)
def load_deletion_request(
    context: dagster.OpExecutionContext,
    config: DataDeletionRequestConfig,
) -> DeletionRequestContext:
    """Load and validate the deletion request, transition to IN_PROGRESS."""
    from django.db import transaction

    with transaction.atomic():
        request = (
            DataDeletionRequest.objects.select_for_update()
            .filter(
                pk=config.request_id,
                status=RequestStatus.APPROVED,
                request_type=RequestType.EVENT_REMOVAL,
            )
            .first()
        )

        if not request:
            raise dagster.Failure(
                f"Request {config.request_id} is not an approved event_removal request.",
            )

        request.status = RequestStatus.IN_PROGRESS
        request.save(update_fields=["status", "updated_at"])

    context.log.info(
        f"Processing deletion request {request.pk}: "
        f"team_id={request.team_id}, events={request.events}, "
        f"time_range={request.start_time} to {request.end_time}, "
        f"execution_mode={request.execution_mode}"
    )
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "events": dagster.MetadataValue.text(", ".join(request.events)),
            "start_time": dagster.MetadataValue.text(str(request.start_time)),
            "end_time": dagster.MetadataValue.text(str(request.end_time)),
            "execution_mode": dagster.MetadataValue.text(request.execution_mode),
        }
    )

    return DeletionRequestContext(
        request_id=str(request.pk),
        team_id=request.team_id,
        start_time=request.start_time,
        end_time=request.end_time,
        events=request.events,
        execution_mode=request.execution_mode,
    )


def _run_immediate_event_deletion(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    deletion_request: DeletionRequestContext,
) -> None:
    table = EVENTS_DATA_TABLE()
    shards = sorted(cluster.shards)

    context.log.info(f"Starting immediate event deletion across {len(shards)} shards on table {table}")

    for idx, shard_num in enumerate(shards, 1):
        context.log.info(f"Processing shard {shard_num} ({idx}/{len(shards)})")
        shard_start = time.monotonic()

        runner = LightweightDeleteMutationRunner(
            table=table,
            predicate=EVENT_REMOVAL_PREDICATE,
            parameters={
                "team_id": deletion_request.team_id,
                "start_time": deletion_request.start_time,
                "end_time": deletion_request.end_time,
                "events": deletion_request.events,
            },
            settings={"lightweight_deletes_sync": 0},
        )

        shard_result = cluster.map_any_host_in_shards({shard_num: runner}).result()
        _host, mutation_waiter = next(iter(shard_result.items()))
        cluster.map_all_hosts_in_shard(shard_num, mutation_waiter.wait).result()

        elapsed = time.monotonic() - shard_start
        context.log.info(f"Shard {shard_num} complete in {elapsed:.1f}s")

    context.add_output_metadata(
        {"mode": dagster.MetadataValue.text("immediate"), "shards_processed": dagster.MetadataValue.int(len(shards))}
    )


def _queue_events_for_deferred_deletion(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    deletion_request: DeletionRequestContext,
) -> None:
    source_table = EVENTS_DATA_TABLE()
    db = django_settings.CLICKHOUSE_DATABASE
    shards = sorted(cluster.shards)
    params = {
        "team_id": deletion_request.team_id,
        "start_time": deletion_request.start_time,
        "end_time": deletion_request.end_time,
        "events": deletion_request.events,
    }
    # nosemgrep: clickhouse-fstring-param-audit (all interpolated values are internal constants/settings)
    insert_sql = (
        f"INSERT INTO {db}.{ADHOC_EVENTS_DELETION_TABLE} (team_id, uuid) "
        f"SELECT team_id, uuid FROM {db}.{source_table} WHERE {EVENT_REMOVAL_PREDICATE}"
    )

    def run_on_shard(client: Client) -> int:
        client.execute(insert_sql, params, settings={"max_execution_time": 1800})
        row = client.execute(
            f"SELECT count() FROM {db}.{ADHOC_EVENTS_DELETION_TABLE} WHERE team_id = %(team_id)s AND is_deleted = 0",
            {"team_id": params["team_id"]},
        )
        return row[0][0] if row else 0

    total_queued = 0
    for idx, shard_num in enumerate(shards, 1):
        context.log.info(f"Queueing shard {shard_num} ({idx}/{len(shards)}) into {ADHOC_EVENTS_DELETION_TABLE}")
        shard_start = time.monotonic()

        shard_result = cluster.map_any_host_in_shards({shard_num: run_on_shard}).result()
        _host, queued = next(iter(shard_result.items()))
        total_queued += queued

        elapsed = time.monotonic() - shard_start
        context.log.info(f"Shard {shard_num}: queued ~{queued} rows in {elapsed:.1f}s")

    context.add_output_metadata(
        {"mode": dagster.MetadataValue.text("deferred"), "queued_rows": dagster.MetadataValue.int(total_queued)}
    )


@dagster.op(tags=OWNER_TAG)
def execute_event_deletion(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> DeletionRequestContext:
    """Dispatch event deletion based on execution_mode."""
    if deletion_request.execution_mode == ExecutionMode.DEFERRED.value:
        _queue_events_for_deferred_deletion(context, cluster, deletion_request)
    else:
        _run_immediate_event_deletion(context, cluster, deletion_request)
    return deletion_request


# ---------------------------------------------------------------------------
# Property removal ops
# ---------------------------------------------------------------------------


@dagster.op(tags=OWNER_TAG)
def load_property_removal_request(
    context: dagster.OpExecutionContext,
    config: DataDeletionRequestConfig,
) -> DeletionRequestContext:
    """Load and validate a property removal request, transition to IN_PROGRESS."""
    from django.db import transaction

    with transaction.atomic():
        request = (
            DataDeletionRequest.objects.select_for_update()
            .filter(
                pk=config.request_id,
                status=RequestStatus.APPROVED,
                request_type=RequestType.PROPERTY_REMOVAL,
            )
            .first()
        )

        if not request:
            raise dagster.Failure(
                f"Request {config.request_id} is not an approved property_removal request.",
            )

        if not request.properties:
            raise dagster.Failure(
                f"Request {config.request_id} has no properties specified.",
            )

        request.status = RequestStatus.IN_PROGRESS
        request.save(update_fields=["status", "updated_at"])

    context.log.info(
        f"Processing property removal {request.pk}: "
        f"team_id={request.team_id}, events={request.events}, "
        f"properties={request.properties}, "
        f"time_range={request.start_time} to {request.end_time}"
    )
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "events": dagster.MetadataValue.text(", ".join(request.events)),
            "properties": dagster.MetadataValue.text(", ".join(request.properties)),
            "start_time": dagster.MetadataValue.text(str(request.start_time)),
            "end_time": dagster.MetadataValue.text(str(request.end_time)),
        }
    )

    return DeletionRequestContext(
        request_id=str(request.pk),
        team_id=request.team_id,
        start_time=request.start_time,
        end_time=request.end_time,
        events=request.events,
        properties=request.properties,
    )


@dagster.op(tags=OWNER_TAG, retry_policy=dagster.RetryPolicy(max_retries=0))
def prepare_and_insert_modified_events(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> DeletionRequestContext:
    """Create temp table, copy events, drop properties, verify, and insert back — all on the same node per shard.

    The temp table is local MergeTree (non-replicated), so every step that
    touches it must execute on the same ClickHouse node. This op runs all
    temp-table work within a single callable per shard to guarantee that.

    After this op, sharded_events temporarily has both the original events
    (with the target properties) and the modified events (without them).
    The next op deletes the originals via a lightweight delete.
    """
    source = EVENTS_DATA_TABLE()
    temp = _temp_table_name(deletion_request.team_id, deletion_request.request_id)
    db = django_settings.CLICKHOUSE_DATABASE
    prop_filter = _property_filter_clause(deletion_request.properties)
    params = _base_params(deletion_request)
    keys = deletion_request.properties

    def process_shard(client: Client) -> dict:
        # 1. Create temp table
        _create_local_staging_table(client, source_table=source, staging_table=temp)

        # 2. Copy matching events (truncate first for idempotency)
        client.execute(f"TRUNCATE TABLE IF EXISTS {db}.{temp}")
        client.execute(
            f"""
            INSERT INTO {db}.{temp}
            SELECT * FROM {db}.{source}
            WHERE team_id = %(team_id)s
              AND timestamp >= %(start_time)s
              AND timestamp < %(end_time)s
              AND event IN %(events)s
              AND {prop_filter}
            """,
            params,
            settings={"max_execution_time": 1800},
        )
        copied = client.execute(f"SELECT count() FROM {db}.{temp}")[0][0]

        # 3. Mutate properties and reset affected DEFAULT materialized columns.
        # Query the distributed table (events) for column comments — sharded_events
        # may not carry them. Queried per-shard to handle schema drift.
        affected_mat_cols = _get_affected_mat_columns(client, "events", keys)

        update_parts = [
            "properties = JSONDropKeys(%(keys)s)(properties)",
            "inserted_at = now()",
        ]
        for col_name, is_nullable in affected_mat_cols:
            default = "NULL" if is_nullable else "''"
            update_parts.append(f"`{col_name}` = {default}")

        runner = AlterTableMutationRunner(
            table=temp,
            commands={f"UPDATE {', '.join(update_parts)} WHERE 1=1"},
            parameters={"keys": keys},
        )
        waiter = runner(client)
        waiter.wait(client)

        # 4. Verify no target properties remain
        verify_params = _property_filter_params(keys)
        remaining = client.execute(
            f"SELECT count() FROM {db}.{temp} WHERE {prop_filter}",
            verify_params,
        )[0][0]
        if remaining > 0:
            raise Exception(f"{remaining} events still have target properties after mutation")

        # 5. Insert modified events back into sharded_events
        client.execute(
            f"INSERT INTO {db}.{source} SELECT * FROM {db}.{temp}",
            settings={"max_execution_time": 1800},
        )

        return {"copied": copied, "remaining_after_verify": remaining}

    shards = sorted(cluster.shards)
    for idx, shard_num in enumerate(shards, 1):
        context.log.info(f"Processing shard {shard_num} ({idx}/{len(shards)})")
        shard_start = time.monotonic()

        result = cluster.map_any_host_in_shards({shard_num: process_shard}).result()
        _host, stats = next(iter(result.items()))

        elapsed = time.monotonic() - shard_start
        context.log.info(f"Shard {shard_num}: copied {stats['copied']} events, insert complete in {elapsed:.1f}s")

    return deletion_request


@dagster.op(tags=OWNER_TAG)
def delete_original_events(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> DeletionRequestContext:
    """Delete the original (unmodified) events that still have the target properties."""
    table = EVENTS_DATA_TABLE()
    prop_filter = _property_filter_clause(deletion_request.properties)

    for shard_num in sorted(cluster.shards):
        context.log.info(f"Deleting originals on shard {shard_num}")
        shard_start = time.monotonic()

        runner = LightweightDeleteMutationRunner(
            table=table,
            predicate=(
                f"team_id = %(team_id)s "
                f"AND timestamp >= %(start_time)s "
                f"AND timestamp < %(end_time)s "
                f"AND event IN %(events)s "
                f"AND {prop_filter}"
            ),
            parameters=_base_params(deletion_request),
            settings={"lightweight_deletes_sync": 0},
        )

        shard_result = cluster.map_any_host_in_shards({shard_num: runner}).result()
        _host, waiter = next(iter(shard_result.items()))
        cluster.map_all_hosts_in_shard(shard_num, waiter.wait).result()

        elapsed = time.monotonic() - shard_start
        context.log.info(f"Shard {shard_num}: delete complete in {elapsed:.1f}s")

    return deletion_request


@dagster.op(tags=OWNER_TAG)
def cleanup_temp_tables(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> DeletionRequestContext:
    """Drop the temp tables on all shards."""
    temp = _temp_table_name(deletion_request.team_id, deletion_request.request_id)
    db = django_settings.CLICKHOUSE_DATABASE

    for shard_num in sorted(cluster.shards):
        cluster.map_any_host_in_shards({shard_num: Query(f"DROP TABLE IF EXISTS {db}.{temp}")}).result()
        context.log.info(f"Shard {shard_num}: temp table dropped")

    return deletion_request


# ---------------------------------------------------------------------------
# Shared ops
# ---------------------------------------------------------------------------


@dagster.op(tags=OWNER_TAG)
def finalize_deletion_request(
    context: dagster.OpExecutionContext,
    deletion_request: DeletionRequestContext,
) -> None:
    """Transition the deletion request out of IN_PROGRESS.

    Immediate → COMPLETED. Deferred → QUEUED (verify sensor promotes later).
    """
    from django.utils import timezone

    if deletion_request.execution_mode == ExecutionMode.DEFERRED.value:
        next_status = RequestStatus.QUEUED
    else:
        next_status = RequestStatus.COMPLETED

    DataDeletionRequest.objects.filter(
        pk=deletion_request.request_id,
        status=RequestStatus.IN_PROGRESS,
    ).update(status=next_status, updated_at=timezone.now())

    context.log.info(f"Deletion request {deletion_request.request_id} marked as {next_status.value}.")


@dagster.failure_hook()
def mark_deletion_failed(context: dagster.HookContext) -> None:
    """Mark the deletion request as failed if any op fails."""
    from django.utils import timezone

    run = context.instance.get_run_by_id(context.run_id)
    if run is None:
        return

    run_config = run.run_config
    if not isinstance(run_config, dict):
        return

    ops_config = run_config.get("ops", {})
    # Check both job types
    request_id = ops_config.get("load_deletion_request", {}).get("config", {}).get("request_id") or ops_config.get(
        "load_property_removal_request", {}
    ).get("config", {}).get("request_id")
    if not request_id:
        return

    DataDeletionRequest.objects.filter(
        pk=request_id,
        status=RequestStatus.IN_PROGRESS,
    ).update(status=RequestStatus.FAILED, updated_at=timezone.now())

    context.log.error(f"Deletion request {request_id} marked as failed.")

    # Clean up temp tables for property removal jobs
    if ops_config.get("load_property_removal_request"):
        try:
            from posthog.clickhouse.cluster import Query, get_cluster

            db_request = DataDeletionRequest.objects.filter(pk=request_id).values("team_id").first()
            if db_request:
                temp = _temp_table_name(db_request["team_id"], request_id)
                db = django_settings.CLICKHOUSE_DATABASE
                cluster = get_cluster()
                cluster.map_one_host_per_shard(Query(f"DROP TABLE IF EXISTS {db}.{temp}")).result()
                context.log.info(f"Cleaned up temp table {temp}")
        except Exception as e:
            context.log.warning(f"Failed to clean up temp table: {e}")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@dagster.job(tags=OWNER_TAG, hooks={mark_deletion_failed})
def data_deletion_request_event_removal():
    """Execute an approved event deletion request.

    Immediate mode runs a lightweight delete mutation shard by shard.
    Deferred mode queues event UUIDs into adhoc_events_deletion for the
    scheduled deletes_job to drain later.
    """
    request = load_deletion_request()
    result = execute_event_deletion(request)
    finalize_deletion_request(result)


@dagster.job(tags=OWNER_TAG, hooks={mark_deletion_failed})
def data_deletion_request_property_removal():
    """Execute an approved property removal request: copy events, drop properties, swap back."""
    request = load_property_removal_request()
    request = prepare_and_insert_modified_events(request)
    request = delete_original_events(request)
    request = cleanup_temp_tables(request)
    finalize_deletion_request(request)


# ---------------------------------------------------------------------------
# Pickup sensor: scans for APPROVED requests and launches jobs (max 1 at a time)
# ---------------------------------------------------------------------------

_DELETION_JOB_NAMES = [
    data_deletion_request_event_removal.name,
    data_deletion_request_property_removal.name,
]


@dagster.sensor(
    jobs=[data_deletion_request_event_removal, data_deletion_request_property_removal],
    minimum_interval_seconds=600,
    default_status=dagster.DefaultSensorStatus.STOPPED,
)
def data_deletion_request_pickup_sensor(context: dagster.SensorEvaluationContext):
    """Poll for APPROVED DataDeletionRequests and launch jobs (max 1 active at a time).

    Operator enables this sensor manually from the Dagster UI when ready to
    process approved requests.
    """
    active_statuses = [
        dagster.DagsterRunStatus.QUEUED,
        dagster.DagsterRunStatus.NOT_STARTED,
        dagster.DagsterRunStatus.STARTING,
        dagster.DagsterRunStatus.STARTED,
    ]
    active_count = 0
    for job_name in _DELETION_JOB_NAMES:
        active_count += len(
            context.instance.get_run_records(
                dagster.RunsFilter(job_name=job_name, statuses=active_statuses),
            )
        )
    if active_count > 0:
        return dagster.SkipReason(f"A deletion job is already running ({active_count} active). Waiting.")

    next_request = DataDeletionRequest.objects.filter(status=RequestStatus.APPROVED).order_by("approved_at").first()
    if next_request is None:
        return dagster.SkipReason("No approved deletion requests to process.")

    if next_request.request_type == RequestType.EVENT_REMOVAL:
        job = data_deletion_request_event_removal
        load_op = "load_deletion_request"
    elif next_request.request_type == RequestType.PROPERTY_REMOVAL:
        job = data_deletion_request_property_removal
        load_op = "load_property_removal_request"
    else:
        return dagster.SkipReason(f"Unknown request_type for request {next_request.pk}: {next_request.request_type}")

    context.log.info(
        f"Launching {job.name} for request {next_request.pk} "
        f"(team_id={next_request.team_id}, type={next_request.request_type})"
    )

    return dagster.RunRequest(
        run_key=str(next_request.pk),
        job_name=job.name,
        run_config={
            "ops": {
                load_op: {
                    "config": {"request_id": str(next_request.pk)},
                },
            },
        },
        tags={"team_id": str(next_request.team_id), "deletion_request_id": str(next_request.pk)},
    )


# ---------------------------------------------------------------------------
# Verifier sensor: promotes QUEUED → COMPLETED once events are gone
# ---------------------------------------------------------------------------


def _count_remaining_matching_events(request: DataDeletionRequest) -> int:
    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.client.connection import ClickHouseUser
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context
    from posthog.clickhouse.workload import Workload

    params = _event_removal_params(request)
    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=request.team_id,
        workload=Workload.OFFLINE,
        query_type="data_deletion_request_verify_queued",
    ):
        # nosemgrep: clickhouse-fstring-param-audit (EVENT_REMOVAL_PREDICATE is a module-level constant)
        result = sync_execute(
            f"SELECT count() FROM events WHERE {EVENT_REMOVAL_PREDICATE} AND _row_exists = 1",
            params,
            team_id=request.team_id,
            readonly=True,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.META,
        )
    return int(result[0][0]) if result else 0


@dagster.run_status_sensor(
    run_status=dagster.DagsterRunStatus.SUCCESS,
    monitored_jobs=[deletes_job],
    default_status=dagster.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=60,
)
def verify_queued_deletion_requests(context: dagster.RunStatusSensorContext):
    """Promote QUEUED deletion requests to COMPLETED once their events are gone.

    Fires after each deletes_job SUCCESS.
    """
    from django.utils import timezone

    queued = DataDeletionRequest.objects.filter(status=RequestStatus.QUEUED)
    promoted = 0
    for request in queued:
        try:
            remaining = _count_remaining_matching_events(request)
        except Exception as exc:
            context.log.warning(f"Could not verify deletion request {request.pk}: {exc}")
            continue

        if remaining > 0:
            context.log.info(
                f"Deletion request {request.pk}: {remaining} matching events remain, keeping status QUEUED."
            )
            continue

        updated = DataDeletionRequest.objects.filter(pk=request.pk, status=RequestStatus.QUEUED).update(
            status=RequestStatus.COMPLETED, updated_at=timezone.now()
        )
        if updated:
            promoted += 1
            context.log.info(f"Deletion request {request.pk} promoted QUEUED → COMPLETED.")

    context.log.info(f"verify_queued_deletion_requests: {promoted} request(s) promoted this cycle.")
