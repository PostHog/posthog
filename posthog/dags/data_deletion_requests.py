import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings as django_settings

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE
from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster, LightweightDeleteMutationRunner
from posthog.dags.common import JobOwners
from posthog.dags.deletes import deletes_job
from posthog.models.data_deletion_request import (
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
    compile_hogql_predicate,
    event_match_params,
    event_match_sql_fragment,
    jsonhas_expr,
)
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.bulk_delete import (
    delete_persons_profile,
    queue_person_recording_deletion,
    resolve_persons_for_deletion,
)

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
    delete_all_events: bool = False
    hogql_predicate: str = ""
    # Set by process_property_removal_per_shard; cleaned re-inserts get this exact value stamped
    # onto inserted_at so the same op's delete pass can exclude them via inserted_at < marker.
    inserted_at_marker: datetime | None = None


@dataclass
class PersonRemovalContext:
    request_id: str
    team_id: int
    person_uuids: list[str]
    person_distinct_ids: list[str]
    drop_profiles: bool
    drop_events: bool
    drop_recordings: bool
    start_time: datetime | None = None
    end_time: datetime | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_execution_attempt(request: DataDeletionRequest) -> None:
    """Mark the request IN_PROGRESS and update execution-tracking fields.

    Called from inside the ``select_for_update`` block of each ``load_*`` op so
    the counter and timestamps are bumped exactly once per APPROVED → IN_PROGRESS
    transition. ``first_executed_at`` is preserved across retries; ``attempt_count``
    counts every actual execution attempt (not Retry button clicks).
    """
    from django.utils import timezone

    now = timezone.now()
    request.status = RequestStatus.IN_PROGRESS
    request.attempt_count = (request.attempt_count or 0) + 1
    request.last_executed_at = now
    update_fields = ["status", "updated_at", "attempt_count", "last_executed_at"]
    if request.first_executed_at is None:
        request.first_executed_at = now
        update_fields.append("first_executed_at")
    request.save(update_fields=update_fields)


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


_EVENT_REMOVAL_TIME_PREDICATE = "team_id = %(team_id)s AND timestamp >= %(start_time)s AND timestamp < %(end_time)s"


def _event_removal_where(obj) -> tuple[str, dict]:
    """Full WHERE predicate + params for event-removal queries.

    Combines the mandatory team/timestamp bounds, the events filter (skipped
    when ``delete_all_events`` is set), and any compiled HogQL predicate. The
    compiled HogQL fragment uses unqualified column references, so the result
    is safe to splice into queries against either the Distributed ``events``
    proxy or the local ``sharded_events`` MergeTree.
    """
    parts = [_EVENT_REMOVAL_TIME_PREDICATE, event_match_sql_fragment(obj)]
    params = event_match_params(obj)
    hogql_sql, hogql_values = compile_hogql_predicate(obj)
    if hogql_sql:
        parts.append(f"AND ({hogql_sql})")
        params.update(hogql_values)
    return " ".join(p for p in parts if p), params


def _mat_col_presence_clauses(mat_cols: list[tuple[str, bool]]) -> list[str]:
    """Per-column "value is present" checks for DEFAULT-materialized property columns.

    Uses ``<col> != ''`` for both nullable and non-nullable variants:

    - The DEFAULT expression (``JSONExtractRaw(properties, prop)``) returns
      ``''`` for missing keys, regardless of whether the column type is
      Nullable. So rows that never carried the property store ``''``, not
      NULL, and ``IS NOT NULL`` would over-match them and pull control rows
      into the copy/delete set.
    - For nullable columns, ``NULL != ''`` evaluates to NULL (treated as
      false in WHERE), so rows we reset to NULL during cleaning are
      correctly skipped by the delete pass.
    - The mutation reset still differs by nullability (NULL vs ``''``), which
      is why ``is_nullable`` is preserved on the input — only the presence
      check is uniform.
    """
    return [f"`{name}` != ''" for name, _ in mat_cols]


def _property_removal_where(
    ctx: DeletionRequestContext,
    mat_cols: list[tuple[str, bool]] | None = None,
    inserted_at_max: str | None = None,
    hogql_compiled: tuple[str, dict] | None = None,
) -> tuple[str, dict]:
    """Full WHERE predicate + params for property-removal queries.

    Used both to copy candidate events into the staging table and to delete the
    originals afterward. The presence check (JSON ``properties`` plus DEFAULT
    materialized columns) MUST match between the two passes — drift causes
    either data loss (delete > copy) or duplication (copy > delete).

    Honors the optional ``hogql_predicate`` on the request the same way
    ``_event_removal_where`` does, so an operator can scope a property removal
    to (e.g.) a specific ``$current_url`` or person property. The compiled
    HogQL fragment uses unqualified column references and is safe to splice
    into queries against either ``events`` or ``sharded_events``. The caller
    must precompile the predicate via ``compile_hogql_predicate`` in the main
    thread (it touches the Django ORM) and pass the result via
    ``hogql_compiled`` — calling it from a per-shard worker thread can fail
    when the worker holds a different DB connection from the test/request
    transaction.

    The delete pass additionally passes ``inserted_at_max``: cleaned re-inserts
    are stamped with that exact value, so ``inserted_at < marker`` skips them.
    Legacy rows may have ``inserted_at IS NULL`` and are still originals to
    delete — the NULL branch keeps them in scope.
    """
    presence_clauses = [_property_filter_clause(ctx.properties)]
    if mat_cols:
        presence_clauses.extend(_mat_col_presence_clauses(mat_cols))
    presence = f"({' OR '.join(presence_clauses)})" if len(presence_clauses) > 1 else presence_clauses[0]

    parts = [
        "team_id = %(team_id)s",
        "AND timestamp >= %(start_time)s",
        "AND timestamp < %(end_time)s",
        "AND event IN %(events)s",
        f"AND {presence}",
    ]
    params = _base_params(ctx)
    if hogql_compiled is not None:
        hogql_sql, hogql_values = hogql_compiled
        if hogql_sql:
            parts.append(f"AND ({hogql_sql})")
            params.update(hogql_values)
    if inserted_at_max is not None:
        # Cast explicitly to DateTime64(6) — without it the parameter is parsed as DateTime
        # (second precision), which truncates microseconds and causes the comparison to skip
        # originals whose inserted_at falls in the same second as the marker. The cleaned
        # re-inserts (which stamp inserted_at = marker via the same parameter) suffer the
        # same truncation in the mutation, so both sides must use the cast.
        parts.append("AND (inserted_at IS NULL OR inserted_at < toDateTime64(%(inserted_at_max)s, 6, 'UTC'))")
        params["inserted_at_max"] = inserted_at_max
    return " ".join(parts), params


QueryLogger = Callable[[str, str], None]


def _get_affected_mat_columns(
    client: Client,
    table: str,
    properties: list[str],
    log: QueryLogger | None = None,
) -> list[tuple[str, bool]]:
    """Query a specific shard for DEFAULT materialized columns matching deleted properties.

    Returns ``(column_name, is_nullable)`` for DEFAULT columns whose comment follows
    the ``column_materializer::properties::<prop>`` convention.  Only DEFAULT columns
    are returned because they are included in ``SELECT *`` (so stale values propagate
    on re-insert) and can be reset via ``ALTER TABLE UPDATE``.  MATERIALIZED columns
    are excluded — ClickHouse recomputes them automatically at insert time.
    """
    database = django_settings.CLICKHOUSE_DATABASE
    sql = """
        SELECT name, comment, type LIKE 'Nullable(%%)'
        FROM system.columns
        WHERE database = %(database)s
          AND table = %(table)s
          AND default_kind = 'DEFAULT'
          AND comment LIKE '%%column_materializer::%%'
          AND comment NOT LIKE '%%column_materializer::elements_chain::%%'
        """
    if log:
        log("discover-mat-cols", sql)
    rows = client.execute(sql, {"database": database, "table": table})

    target_props = set(properties)
    result: list[tuple[str, bool]] = []
    for col_name, comment, is_nullable in rows:
        details = MaterializedColumnDetails.from_column_comment(comment)
        if details.table_column == "properties" and details.property_name in target_props:
            result.append((col_name, bool(is_nullable)))
    return result


def _create_local_staging_table(
    client: Client,
    source_table: str,
    staging_table: str,
    log: QueryLogger | None = None,
) -> None:
    """Create a non-replicated local copy of the source table schema."""
    database = django_settings.CLICKHOUSE_DATABASE

    exists_sql = "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(table)s"
    if log:
        log("temp-exists-check", exists_sql)
    rows = client.execute(exists_sql, {"db": database, "table": staging_table})
    if rows[0][0] > 0:
        return

    engine_sql = "SELECT engine_full FROM system.tables WHERE database = %(db)s AND name = %(table)s"
    if log:
        log("source-engine-lookup", engine_sql)
    rows = client.execute(engine_sql, {"db": database, "table": source_table})
    if not rows:
        raise dagster.Failure(description=f"Source table {database}.{source_table} not found")

    create_sql = (
        f"CREATE TABLE IF NOT EXISTS {database}.{staging_table} AS {database}.{source_table} ENGINE = MergeTree()"
    )
    if log:
        log("create-temp", create_sql)
    client.execute(create_sql)


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

        _record_execution_attempt(request)

    events_desc = "<all events>" if request.delete_all_events else f"{request.events}"
    context.log.info(
        f"Processing deletion request {request.pk}: "
        f"team_id={request.team_id}, events={events_desc}, "
        f"time_range={request.start_time} to {request.end_time}, "
        f"execution_mode={request.execution_mode}, "
        f"hogql_predicate={request.hogql_predicate or '<none>'}"
    )
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "events": dagster.MetadataValue.text(
                "<all events>" if request.delete_all_events else ", ".join(request.events)
            ),
            "start_time": dagster.MetadataValue.text(str(request.start_time)),
            "end_time": dagster.MetadataValue.text(str(request.end_time)),
            "execution_mode": dagster.MetadataValue.text(request.execution_mode),
            "delete_all_events": dagster.MetadataValue.bool(request.delete_all_events),
            "hogql_predicate": dagster.MetadataValue.text(request.hogql_predicate or ""),
        }
    )

    assert request.start_time is not None and request.end_time is not None
    return DeletionRequestContext(
        request_id=str(request.pk),
        team_id=request.team_id,
        start_time=request.start_time,
        end_time=request.end_time,
        events=request.events,
        execution_mode=request.execution_mode,
        delete_all_events=request.delete_all_events,
        hogql_predicate=request.hogql_predicate or "",
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

        predicate, parameters = _event_removal_where(deletion_request)
        runner = LightweightDeleteMutationRunner(
            table=table,
            predicate=predicate,
            parameters=parameters,
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
    predicate, params = _event_removal_where(deletion_request)
    # nosemgrep: clickhouse-fstring-param-audit (all interpolated values are internal constants/settings)
    insert_sql = (
        f"INSERT INTO {db}.{ADHOC_EVENTS_DELETION_TABLE} (team_id, uuid) "
        f"SELECT team_id, uuid FROM {db}.{source_table} WHERE {predicate}"
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

        _record_execution_attempt(request)

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
            "hogql_predicate": dagster.MetadataValue.text(request.hogql_predicate or ""),
        }
    )

    assert request.start_time is not None and request.end_time is not None
    return DeletionRequestContext(
        request_id=str(request.pk),
        team_id=request.team_id,
        start_time=request.start_time,
        end_time=request.end_time,
        events=request.events,
        properties=request.properties,
        hogql_predicate=request.hogql_predicate or "",
    )


@dagster.op(tags=OWNER_TAG, retry_policy=dagster.RetryPolicy(max_retries=0))
def process_property_removal_per_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> DeletionRequestContext:
    """Run the full property-removal cycle one shard at a time.

    Per shard, on a single host (the temp table is local non-replicated MergeTree):

      1. Discover affected DEFAULT materialized columns.
      2. Create the temp table.
      3. Copy matching events from sharded_events into temp. Presence check covers
         JSON ``properties`` AND materialized columns — a row can carry the value
         in the column alone, and ``SELECT *`` would otherwise leave it behind.
      4. Mutate the temp table: drop JSON keys, reset materialized columns to their
         defaults, stamp ``inserted_at = marker``.
      5. Verify no target presence remains in temp (JSON or materialized columns).
      6. Re-insert cleaned events into sharded_events.
      7. Lightweight-delete the originals from sharded_events. Same presence check
         as the copy, plus ``inserted_at IS NULL OR inserted_at < marker`` so the
         cleaned re-inserts (stamped with that exact marker) are skipped.
      8. Drop the temp table.

    Steps 3 and 7 use the same predicate (modulo the ``inserted_at`` clause on
    delete), generated by ``_property_removal_where`` from the same per-shard
    ``mat_cols`` list, so they cannot drift.
    """
    from django.utils import timezone

    source = EVENTS_DATA_TABLE()
    temp = _temp_table_name(deletion_request.team_id, deletion_request.request_id)
    db = django_settings.CLICKHOUSE_DATABASE
    properties = deletion_request.properties
    marker = timezone.now()
    deletion_request.inserted_at_marker = marker
    # Format the marker as a string with microseconds — clickhouse-driver serializes Python
    # datetime values with second precision, which causes the cleaned re-inserts to be stamped
    # with a truncated inserted_at and the originals-delete predicate to mismatch by sub-second
    # offsets. Passing as ISO string and casting in SQL preserves the full precision.
    marker_str = marker.strftime("%Y-%m-%d %H:%M:%S.%f")
    # HogQL compilation reaches into the Django ORM (Team lookup); compile once on the main
    # thread before dispatching per-shard work, otherwise the worker thread's DB connection
    # may not see the request/test transaction.
    hogql_compiled = compile_hogql_predicate(deletion_request)

    def _flatten_sql(sql: str) -> str:
        return " ".join(sql.split())

    def process_shard(client: Client) -> dict:
        def log_query(label: str, sql: str) -> None:
            context.log.info(f"[{label}] {_flatten_sql(sql)}")

        def execute(label: str, sql: str, params=None, settings=None):
            log_query(label, sql)
            return client.execute(sql, params, settings=settings)

        affected_mat_cols = _get_affected_mat_columns(client, "events", properties, log=log_query)
        context.log.info(f"affected materialized columns: {[c[0] for c in affected_mat_cols]}")

        _create_local_staging_table(client, source_table=source, staging_table=temp, log=log_query)

        copy_predicate, copy_params = _property_removal_where(
            deletion_request,
            mat_cols=affected_mat_cols,
            hogql_compiled=hogql_compiled,
        )
        execute("truncate-temp", f"TRUNCATE TABLE IF EXISTS {db}.{temp}")
        execute(
            "copy-into-temp",
            f"INSERT INTO {db}.{temp} SELECT * FROM {db}.{source} WHERE {copy_predicate}",
            copy_params,
            settings={"max_execution_time": 1800},
        )
        copied = execute("count-temp", f"SELECT count() FROM {db}.{temp}")[0][0]

        update_parts = [
            "properties = JSONDropKeys(%(keys)s)(properties)",
            # Cast to DateTime64(6) so microseconds survive the parameter binding —
            # mirrors the cast in the delete predicate so both sides agree on the marker.
            "inserted_at = toDateTime64(%(inserted_at_marker)s, 6, 'UTC')",
        ]
        for col_name, is_nullable in affected_mat_cols:
            default = "NULL" if is_nullable else "''"
            update_parts.append(f"`{col_name}` = {default}")

        clean_runner = AlterTableMutationRunner(
            table=temp,
            commands={f"UPDATE {', '.join(update_parts)} WHERE 1=1"},
            parameters={"keys": properties, "inserted_at_marker": marker_str},
        )
        context.log.info(
            f"[clean-temp-mutation] {_flatten_sql(clean_runner.get_statement(clean_runner.get_all_commands()))}"
        )
        clean_waiter = clean_runner(client)
        clean_waiter.wait(client)

        verify_clauses = [_property_filter_clause(properties), *_mat_col_presence_clauses(affected_mat_cols)]
        verify_predicate = f"({' OR '.join(verify_clauses)})" if len(verify_clauses) > 1 else verify_clauses[0]
        verify_params = _property_filter_params(properties)
        remaining = execute(
            "verify-temp-clean",
            f"SELECT count() FROM {db}.{temp} WHERE {verify_predicate}",
            verify_params,
        )[0][0]
        if remaining > 0:
            raise Exception(f"{remaining} events still carry target properties after mutation")

        execute(
            "insert-cleaned-back",
            f"INSERT INTO {db}.{source} SELECT * FROM {db}.{temp}",
            settings={"max_execution_time": 1800},
        )

        # Submit the originals delete. Returns a waiter so the outer loop can block on
        # all replicas of this shard before moving on to the next shard.
        delete_predicate, delete_params = _property_removal_where(
            deletion_request,
            mat_cols=affected_mat_cols,
            inserted_at_max=marker_str,
            hogql_compiled=hogql_compiled,
        )
        delete_runner = LightweightDeleteMutationRunner(
            table=source,
            predicate=delete_predicate,
            parameters=delete_params,
            settings={"lightweight_deletes_sync": 2, "mutations_sync": 2},
        )
        context.log.info(
            f"[delete-originals] {_flatten_sql(delete_runner.get_statement(delete_runner.get_all_commands()))}"
        )
        delete_waiter = delete_runner(client)
        # Wait locally so we can be sure the delete is fully applied before this op moves on
        # to the next shard or returns. ``mutations_sync = 2`` makes the runner block on all
        # replicas of the originating shard; the explicit ``wait`` is a defensive backstop.
        delete_waiter.wait(client)

        # Drop the temp table on the SAME host that created it. The temp table is local
        # non-replicated MergeTree; a separate ``map_any_host_in_shards`` call from the outer
        # loop can resolve to a different replica (the schema-qualified name does not
        # influence host selection), which would silently DROP IF EXISTS on the wrong host
        # and leave the staging rows behind on the originating one.
        execute("drop-temp", f"DROP TABLE IF EXISTS {db}.{temp}")

        return {"copied": copied}

    shards = sorted(cluster.shards)
    for idx, shard_num in enumerate(shards, 1):
        context.log.info(f"Processing shard {shard_num} ({idx}/{len(shards)})")
        shard_start = time.monotonic()

        result = cluster.map_any_host_in_shards({shard_num: process_shard}).result()
        _host, stats = next(iter(result.items()))

        elapsed = time.monotonic() - shard_start
        context.log.info(
            f"Shard {shard_num}: copied {stats['copied']} events, originals deleted, temp dropped in {elapsed:.1f}s"
        )

    return deletion_request


# ---------------------------------------------------------------------------
# Person removal ops
# ---------------------------------------------------------------------------


@dagster.op(tags=OWNER_TAG)
def load_person_removal_request(
    context: dagster.OpExecutionContext,
    config: DataDeletionRequestConfig,
) -> PersonRemovalContext:
    """Load and validate a person_removal request, transition to IN_PROGRESS."""
    from django.db import transaction

    with transaction.atomic():
        request = (
            DataDeletionRequest.objects.select_for_update()
            .filter(
                pk=config.request_id,
                status=RequestStatus.APPROVED,
                request_type=RequestType.PERSON_REMOVAL,
            )
            .first()
        )

        if not request:
            raise dagster.Failure(
                f"Request {config.request_id} is not an approved person_removal request.",
            )

        # Defense-in-depth: model.clean() enforces this, but a corrupt row would silently lose
        # one of the selectors in resolve_persons_for_deletion (which uses if/elif).
        if request.person_uuids and request.person_distinct_ids:
            raise dagster.Failure(
                f"Request {config.request_id} has both person_uuids and person_distinct_ids set; "
                "they are mutually exclusive."
            )

        _record_execution_attempt(request)

    # The fields are nullable on the model (NULL for non-person_removal rows), but
    # PersonRemovalContext and the downstream `if not drop_x` consumers want plain bools.
    # model.clean() guarantees at least one is True for person_removal requests.
    drop_profiles = bool(request.person_drop_profiles)
    drop_events = bool(request.person_drop_events)
    drop_recordings = bool(request.person_drop_recordings)

    context.log.info(
        f"Processing person_removal request {request.pk}: "
        f"team_id={request.team_id}, "
        f"uuids={len(request.person_uuids)}, distinct_ids={len(request.person_distinct_ids)}, "
        f"drop_profiles={drop_profiles}, "
        f"drop_events={drop_events}, "
        f"drop_recordings={drop_recordings}"
    )
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "uuid_count": dagster.MetadataValue.int(len(request.person_uuids)),
            "distinct_id_count": dagster.MetadataValue.int(len(request.person_distinct_ids)),
            "drop_profiles": dagster.MetadataValue.bool(drop_profiles),
            "drop_events": dagster.MetadataValue.bool(drop_events),
            "drop_recordings": dagster.MetadataValue.bool(drop_recordings),
        }
    )

    return PersonRemovalContext(
        request_id=str(request.pk),
        team_id=request.team_id,
        person_uuids=[str(u) for u in request.person_uuids],
        person_distinct_ids=list(request.person_distinct_ids),
        drop_profiles=drop_profiles,
        drop_events=drop_events,
        drop_recordings=drop_recordings,
        start_time=request.start_time,
        end_time=request.end_time,
    )


def _person_event_predicate(ctx: PersonRemovalContext) -> tuple[str, dict]:
    """Build WHERE predicate + params for events linked to the targeted persons."""
    parts = ["team_id = %(team_id)s AND person_id IN %(person_ids)s"]
    params: dict = {"team_id": ctx.team_id, "person_ids": ctx.person_uuids}
    if ctx.start_time is not None and ctx.end_time is not None:
        parts.append("AND timestamp >= %(start_time)s AND timestamp < %(end_time)s")
        params["start_time"] = ctx.start_time
        params["end_time"] = ctx.end_time
    return " ".join(parts), params


@dagster.op(tags=OWNER_TAG)
def delete_person_events_op(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    person_removal: PersonRemovalContext,
) -> PersonRemovalContext:
    """Per-shard lightweight delete of events for the targeted persons."""
    if not person_removal.drop_events:
        context.log.info("drop_events=False, skipping event deletion")
        return person_removal
    # The CH events table is keyed by person_id (UUID), so resolve distinct_ids → uuids when
    # the request was submitted by distinct_id. Selectors are mutually exclusive (enforced in
    # DataDeletionRequest._clean_person_removal and re-checked in load_person_removal_request).
    if person_removal.person_distinct_ids:
        persons = resolve_persons_for_deletion(
            person_removal.team_id,
            uuids=None,
            distinct_ids=person_removal.person_distinct_ids,
        )
        person_removal.person_uuids = [str(p.uuid) for p in persons]
    if not person_removal.person_uuids:
        context.log.info("No persons resolved; nothing to delete")
        return person_removal

    table = EVENTS_DATA_TABLE()
    predicate, params = _person_event_predicate(person_removal)
    shards = sorted(cluster.shards)
    context.log.info(f"Deleting events for {len(person_removal.person_uuids)} persons across {len(shards)} shards")

    for idx, shard_num in enumerate(shards, 1):
        context.log.info(f"Processing shard {shard_num} ({idx}/{len(shards)})")
        shard_start = time.monotonic()
        runner = LightweightDeleteMutationRunner(
            table=table,
            predicate=predicate,
            parameters=params,
            settings={"lightweight_deletes_sync": 0},
        )
        shard_result = cluster.map_any_host_in_shards({shard_num: runner}).result()
        _host, waiter = next(iter(shard_result.items()))
        cluster.map_all_hosts_in_shard(shard_num, waiter.wait).result()
        context.log.info(f"Shard {shard_num} complete in {time.monotonic() - shard_start:.1f}s")

    context.add_output_metadata({"shards_processed": dagster.MetadataValue.int(len(shards))})
    return person_removal


@dagster.op(tags=OWNER_TAG)
def delete_person_recordings_op(
    context: dagster.OpExecutionContext,
    person_removal: PersonRemovalContext,
) -> PersonRemovalContext:
    """Queue recording deletion via Temporal for the targeted persons."""
    if not person_removal.drop_recordings:
        context.log.info("drop_recordings=False, skipping recording deletion")
        return person_removal

    persons = resolve_persons_for_deletion(
        person_removal.team_id,
        uuids=person_removal.person_uuids or None,
        distinct_ids=person_removal.person_distinct_ids or None,
    )
    if not persons:
        context.log.info("No persons resolved; nothing to delete")
        return person_removal

    queue_person_recording_deletion(person_removal.team_id, persons, actor=None)
    context.add_output_metadata({"recording_workflows": dagster.MetadataValue.int(len(persons))})
    return person_removal


@dagster.op(tags=OWNER_TAG)
def delete_person_profiles_op(
    context: dagster.OpExecutionContext,
    person_removal: PersonRemovalContext,
) -> PersonRemovalContext:
    """Tombstone Person rows in CH and delete from Postgres, last.

    On per-person failures, errors are recorded in op metadata and the request is allowed to
    transition to COMPLETED — Postgres rows remain for the failed UUIDs and the operator can
    submit a follow-up request for them. This mirrors the best-effort semantics of the
    `POST /api/projects/:id/persons/bulk_delete/` endpoint and avoids flipping the whole
    request to FAILED after upstream events/recordings ops have already done their work.
    """
    if not person_removal.drop_profiles:
        context.log.info("drop_profiles=False, skipping profile deletion")
        return person_removal

    persons = resolve_persons_for_deletion(
        person_removal.team_id,
        uuids=person_removal.person_uuids or None,
        distinct_ids=person_removal.person_distinct_ids or None,
    )
    if not persons:
        context.log.info("No persons resolved; nothing to delete")
        return person_removal

    result = delete_persons_profile(person_removal.team_id, persons, actor=None)
    metadata: dict[str, dagster.MetadataValue] = {
        "deleted_count": dagster.MetadataValue.int(result.deleted_count),
        "errors": dagster.MetadataValue.int(len(result.errors)),
    }
    if result.errors:
        context.log.warning(
            f"Person profile deletion had {len(result.errors)} per-person failures; "
            f"Postgres rows remain for failed UUIDs and can be retried via a follow-up request"
        )
        metadata["error_uuids"] = dagster.MetadataValue.text(", ".join(str(u) for u in result.errors))
    context.add_output_metadata(metadata)
    return person_removal


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


@dagster.op(tags=OWNER_TAG)
def finalize_person_removal(
    context: dagster.OpExecutionContext,
    person_removal: PersonRemovalContext,
) -> None:
    """Mark a person_removal request as COMPLETED."""
    from django.utils import timezone

    DataDeletionRequest.objects.filter(
        pk=person_removal.request_id,
        status=RequestStatus.IN_PROGRESS,
    ).update(status=RequestStatus.COMPLETED, updated_at=timezone.now())

    context.log.info(f"Person removal request {person_removal.request_id} marked as completed.")


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
    # Check all job types
    request_id = (
        ops_config.get("load_deletion_request", {}).get("config", {}).get("request_id")
        or ops_config.get("load_property_removal_request", {}).get("config", {}).get("request_id")
        or ops_config.get("load_person_removal_request", {}).get("config", {}).get("request_id")
    )
    if not request_id:
        return

    DataDeletionRequest.objects.filter(
        pk=request_id,
        status=RequestStatus.IN_PROGRESS,
    ).update(status=RequestStatus.FAILED, updated_at=timezone.now())

    context.log.error(f"Deletion request {request_id} marked as failed.")

    # Clean up temp tables for property removal jobs. The temp table is local
    # non-replicated MergeTree, so it only exists on whichever host originally ran
    # ``process_shard`` for that shard. We don't know which host that was at this
    # point, so broadcast the DROP to every host in every shard — DROP IF EXISTS
    # is a safe no-op on hosts that don't have it.
    if ops_config.get("load_property_removal_request"):
        try:
            from posthog.clickhouse.cluster import Query, get_cluster

            db_request = DataDeletionRequest.objects.filter(pk=request_id).values("team_id").first()
            if db_request:
                temp = _temp_table_name(db_request["team_id"], request_id)
                db = django_settings.CLICKHOUSE_DATABASE
                cluster = get_cluster()
                drop_sql = f"DROP TABLE IF EXISTS {db}.{temp}"
                cluster.map_all_hosts(Query(drop_sql)).result()
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
    """Execute an approved property removal request: per shard, copy events, drop properties,
    re-insert, delete originals, drop temp."""
    request = load_property_removal_request()
    request = process_property_removal_per_shard(request)
    finalize_deletion_request(request)


@dagster.job(tags=OWNER_TAG, hooks={mark_deletion_failed})
def data_deletion_request_person_removal():
    """Execute an approved person_removal request: events → recordings → profiles.

    Profiles are deleted last so that earlier ops can still resolve person UUIDs and
    distinct_ids from the Postgres Person row while running.
    """
    request = load_person_removal_request()
    request = delete_person_events_op(request)
    request = delete_person_recordings_op(request)
    request = delete_person_profiles_op(request)
    finalize_person_removal(request)


# ---------------------------------------------------------------------------
# Pickup sensor: scans for APPROVED requests and launches jobs (max 1 at a time)
# ---------------------------------------------------------------------------

_DELETION_JOB_NAMES = [
    data_deletion_request_event_removal.name,
    data_deletion_request_property_removal.name,
    data_deletion_request_person_removal.name,
]


@dagster.sensor(
    jobs=[
        data_deletion_request_event_removal,
        data_deletion_request_property_removal,
        data_deletion_request_person_removal,
    ],
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
        job, load_op = data_deletion_request_event_removal, "load_deletion_request"
    elif next_request.request_type == RequestType.PROPERTY_REMOVAL:
        job, load_op = data_deletion_request_property_removal, "load_property_removal_request"
    elif next_request.request_type == RequestType.PERSON_REMOVAL:
        job, load_op = data_deletion_request_person_removal, "load_person_removal_request"
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

    predicate, params = _event_removal_where(request)
    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=request.team_id,
        workload=Workload.OFFLINE,
        query_type="data_deletion_request_verify_queued",
    ):
        # nosemgrep: clickhouse-fstring-param-audit (predicate built from internal helper, not user input)
        result = sync_execute(
            f"SELECT count() FROM events WHERE {predicate} AND _row_exists = 1",
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
