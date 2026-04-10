import time
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings as django_settings

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.cluster import (
    AlterTableMutationRunner,
    ClickhouseCluster,
    LightweightDeleteMutationRunner,
    Query,
)
from posthog.dags.common import JobOwners
from posthog.models.data_deletion_request import DataDeletionRequest, RequestStatus, RequestType
from posthog.models.event.sql import EVENTS_DATA_TABLE

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _temp_table_name(team_id: int, request_id: str) -> str:
    return f"tmp_dag_team_{team_id}_prop_rm_{request_id[:8]}"


def _property_filter_clause(properties: list[str]) -> str:
    if len(properties) == 1:
        return "JSONHas(properties, %(filter_property)s)"
    return "hasAny(JSONExtractKeys(properties), %(filter_properties)s)"


def _property_filter_params(properties: list[str]) -> dict:
    if len(properties) == 1:
        return {"filter_property": properties[0]}
    return {"filter_properties": properties}


def _base_params(ctx: DeletionRequestContext) -> dict:
    return {
        "team_id": ctx.team_id,
        "start_time": ctx.start_time,
        "end_time": ctx.end_time,
        "events": ctx.events,
        **_property_filter_params(ctx.properties),
    }


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
        f"time_range={request.start_time} to {request.end_time}"
    )
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "events": dagster.MetadataValue.text(", ".join(request.events)),
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
    )


@dagster.op(tags=OWNER_TAG)
def execute_event_deletion(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> DeletionRequestContext:
    """Execute lightweight deletes on each shard serially."""
    table = EVENTS_DATA_TABLE()
    shards = sorted(cluster.shards)
    total_shards = len(shards)

    context.log.info(f"Starting event deletion across {total_shards} shards on table {table}")

    for idx, shard_num in enumerate(shards, 1):
        context.log.info(f"Processing shard {shard_num} ({idx}/{total_shards})")
        shard_start = time.monotonic()

        runner = LightweightDeleteMutationRunner(
            table=table,
            predicate=(
                "team_id = %(team_id)s "
                "AND timestamp >= %(start_time)s "
                "AND timestamp < %(end_time)s "
                "AND event IN %(events)s"
            ),
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
        {
            "shards_processed": dagster.MetadataValue.int(total_shards),
            "table": dagster.MetadataValue.text(table),
        }
    )

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

        # 3. Mutate properties
        runner = AlterTableMutationRunner(
            table=temp,
            commands={"UPDATE properties = JSONDropKeys(%(keys)s)(properties), inserted_at = now() WHERE 1=1"},
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
def mark_deletion_complete(
    context: dagster.OpExecutionContext,
    deletion_request: DeletionRequestContext,
) -> None:
    """Mark the deletion request as completed."""
    from django.utils import timezone

    DataDeletionRequest.objects.filter(
        pk=deletion_request.request_id,
        status=RequestStatus.IN_PROGRESS,
    ).update(status=RequestStatus.COMPLETED, updated_at=timezone.now())

    context.log.info(f"Deletion request {deletion_request.request_id} marked as completed.")


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
    """Execute an approved event deletion request by running lightweight deletes shard by shard."""
    request = load_deletion_request()
    result = execute_event_deletion(request)
    mark_deletion_complete(result)


@dagster.job(tags=OWNER_TAG, hooks={mark_deletion_failed})
def data_deletion_request_property_removal():
    """Execute an approved property removal request: copy events, drop properties, swap back."""
    request = load_property_removal_request()
    request = prepare_and_insert_modified_events(request)
    request = delete_original_events(request)
    request = cleanup_temp_tables(request)
    mark_deletion_complete(request)
