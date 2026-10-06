import json
import time
import logging
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TypeVar

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError as DjangoValidationError

import dagster
import pydantic
from clickhouse_driver import Client

# Pre-warm the HogQL → HogVM bytecode import chain at code-location load time. Compiling a
# predicate (process_property_removal_shard → compile_hogql_predicate) builds the HogQL
# database, whose virtual-field placeholder replacement lazily does
# ``from common.hogvm.python.execute import …`` (posthog/hogql/placeholders.py). That import
# first runs during op execution, when the Dagster run worker can no longer resolve the
# top-level ``common`` namespace package off sys.path — yielding "No module named 'common'".
# Importing it here, while the worker is still loading op modules with the repo root resolvable,
# caches the chain in sys.modules so the op-time lazy import is a cache hit. Regular posthog.*
# packages already get cached this way; common.hogvm is the only fresh import on the predicate
# path, so it is the one that breaks without this.
import posthog.hogql.compiler.bytecode  # noqa: F401

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, NodeRole
from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    LightweightDeleteMutationRunner,
    wait_for_patch_part_replication,
)
from posthog.clickhouse.events_json import UNPARSEABLE_PROPERTIES_KEY
from posthog.clickhouse.workload import Workload
from posthog.dags.common import JobOwners
from posthog.dags.common.s3_staging import S3StagingLocation
from posthog.dags.deletes import deletes_job
from posthog.data_deletion import compile_event_uuid_query
from posthog.dataclasses import frozen
from posthog.models.data_deletion_request import (
    AUTO_APPROVE_INTERVAL_MINUTES,
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
    auto_approve_pending_requests,
    compile_hogql_predicate,
    event_match_sql_fragment,
    event_removal_where,
    jsonhas_expr,
    portable_event_removal_where,
    verify_queued_request,
)
from posthog.models.deletion_targets import (
    COVERAGE_DOC,
    FLAG_EVALUATIONS,
    PERSONAL_DATA_TARGETS,
    DeletionTarget,
    NotCounted,
    TargetPlacement,
    UnsweepableRowsError,
    UnsweptRowsError,
    assert_no_unsweepable_rows,
    assert_sweep_complete,
    placement_for,
    resolve_placements,
    surviving_rows_sql,
)
from posthog.models.event.sql import json_property_presence_expr
from posthog.models.person.bulk_delete import (
    PersonDeletionStep,
    delete_persons_profile,
    queue_person_recording_deletion,
    resolve_persons_for_deletion,
)

from ee.clickhouse.materialized_columns.columns import MaterializedColumnDetails

OWNER_TAG = {"owner": JobOwners.TEAM_CLICKHOUSE.value}

T = TypeVar("T")


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
    person_properties: list[str] = field(default_factory=list)
    execution_mode: str = ExecutionMode.IMMEDIATE.value
    delete_all_events: bool = False
    hogql_predicate: str = ""
    # Set by load_property_removal_request from the persisted request field; cleaned re-inserts
    # get this exact value stamped onto inserted_at so the delete pass can exclude them via
    # inserted_at < marker, and re-runs recognize rows already cleaned by earlier attempts.
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


@dataclass(frozen=True)
class HogQLEventRemovalContext:
    request_id: str
    team_id: int
    created_by_id: int
    query: str
    variables: dict[str, dict[str, object]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_execution_attempt(request: DataDeletionRequest, run_id: str) -> None:
    """Mark the request IN_PROGRESS and update execution-tracking fields.

    Called from inside the ``select_for_update`` block of each ``load_*`` op so
    the counter, timestamps and Dagster run id are set exactly once per
    APPROVED → IN_PROGRESS transition. ``first_executed_at`` is preserved across
    retries; ``attempt_count`` counts every actual execution attempt (not Retry
    button clicks). ``last_dagster_run_id`` always points at the newest run, so an
    operator debugging a stuck or failed request can jump straight to its logs.
    """
    from django.utils import timezone

    now = timezone.now()
    request.status = RequestStatus.IN_PROGRESS
    request.attempt_count = (request.attempt_count or 0) + 1
    request.last_executed_at = now
    request.last_dagster_run_id = run_id
    update_fields = ["status", "updated_at", "attempt_count", "last_executed_at", "last_dagster_run_id"]
    if request.first_executed_at is None:
        request.first_executed_at = now
        update_fields.append("first_executed_at")
    request.save(update_fields=update_fields)


def _property_filter_clause(props: list[str], prefix: str = "fp_", column: str = "properties") -> str:
    if len(props) == 1:
        return jsonhas_expr(props[0], f"{prefix}0", column=column)
    exprs = [jsonhas_expr(prop, f"{prefix}{i}", column=column) for i, prop in enumerate(props)]
    return f"({' OR '.join(exprs)})"


def _json_property_filter_clause(props: list[str], column: str = "properties") -> str:
    """Find retained copies in native properties, mutation instructions, and quarantine."""
    exprs = [json_property_presence_expr(column, prop) for prop in props]
    # Malformed quarantine can contain any requested value, so its presence prevents verifying removal.
    exprs.append(json_property_presence_expr(column, UNPARSEABLE_PROPERTIES_KEY))
    temporary_props = (
        props
        if column == "properties"
        else [f"{instruction}.{prop}" for instruction in ("$set", "$set_once") for prop in props]
    )
    exprs.extend(json_property_presence_expr("temporary_properties", prop) for prop in temporary_props)
    return f"({' OR '.join(exprs)})"


def _property_filter_params(props: list[str], prefix: str = "fp_") -> dict:
    params: dict[str, str] = {}
    for i, prop in enumerate(props):
        for j, part in enumerate(prop.split(".")):
            params[f"{prefix}{i}_{j}"] = part
    return params


def _base_params(ctx: DeletionRequestContext) -> dict:
    params: dict = {
        "team_id": ctx.team_id,
        "start_time": ctx.start_time,
        "end_time": ctx.end_time,
        **_property_filter_params(ctx.properties),
    }
    if not ctx.delete_all_events:
        params["events"] = ctx.events
    if ctx.person_properties:
        params.update(_property_filter_params(ctx.person_properties, prefix="pp_"))
    return params


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
    person_mat_cols: list[tuple[str, bool]] | None = None,
    inserted_at_max: str | None = None,
    hogql_compiled: tuple[str, dict] | None = None,
    json_schema: bool = False,
) -> tuple[str, dict]:
    """Full WHERE predicate + params for property-removal queries.

    Used both to copy candidate events into the S3 staging copy and to delete the
    originals afterward. The presence check (JSON ``properties`` and/or
    ``person_properties`` plus DEFAULT materialized columns) MUST match between
    the two passes — drift causes either data loss (delete > copy) or duplication
    (copy > delete). For the same reason both passes MUST pass the identical
    ``inserted_at_max``: a row ingested after the marker that only the copy pass
    sees gets a cleaned twin whose original is never deleted.

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

    ``inserted_at_max`` bounds both passes: cleaned re-inserts are stamped with
    that exact value, so ``inserted_at < marker`` skips them. Legacy rows may
    have ``inserted_at IS NULL`` and are still originals to delete — the NULL
    branch keeps them in scope.
    """
    presence_clauses: list[str] = []
    if ctx.properties:
        presence_clauses.append(
            _json_property_filter_clause(ctx.properties, column="properties")
            if json_schema
            else _property_filter_clause(ctx.properties)
        )
    elif json_schema and ctx.person_properties:
        presence_clauses.append(json_property_presence_expr("properties", UNPARSEABLE_PROPERTIES_KEY))
    if mat_cols:
        presence_clauses.extend(_mat_col_presence_clauses(mat_cols))
    if ctx.person_properties:
        presence_clauses.append(
            _json_property_filter_clause(ctx.person_properties, column="person_properties")
            if json_schema
            else _property_filter_clause(ctx.person_properties, prefix="pp_", column="person_properties")
        )
    if person_mat_cols:
        presence_clauses.extend(_mat_col_presence_clauses(person_mat_cols))
    if not presence_clauses:
        raise ValueError(
            "_property_removal_where requires at least one of properties or person_properties to be non-empty"
        )
    presence = f"({' OR '.join(presence_clauses)})" if len(presence_clauses) > 1 else presence_clauses[0]

    parts = [
        "team_id = %(team_id)s",
        "AND timestamp >= %(start_time)s",
        "AND timestamp < %(end_time)s",
        event_match_sql_fragment(ctx),  # empty when delete_all_events is set
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
    return " ".join(p for p in parts if p), params


QueryLogger = Callable[[str, str], None]


def _get_affected_mat_columns(
    client: Client,
    table: str,
    properties: list[str],
    table_column: str = "properties",
    log: QueryLogger | None = None,
) -> list[tuple[str, bool]]:
    """Query a specific shard for materialized columns matching deleted properties.

    Returns ``(column_name, is_nullable)`` for columns whose comment follows the
    ``column_materializer::<table_column>::<prop>`` convention.  Pass
    ``table_column="person_properties"`` to discover columns materialised from
    ``events.person_properties``.  Comments live on the distributed ``events``
    table while the DEFAULT expression lives on ``sharded_events`` (see
    ``materialize()`` in ee/clickhouse/materialized_columns), so we cannot
    filter by ``default_kind`` on the same row that carries the comment.
    The comment itself is a sufficient identifier — it is PostHog-specific and the
    ``elements_chain::*`` family is excluded explicitly.

    Callers pass the target's Distributed read table, because that is where events keeps the
    comments. flag_evaluations declares the same comments on its read table for its typed columns.
    """
    database = django_settings.CLICKHOUSE_DATABASE
    sql = """
        SELECT name, comment, type LIKE 'Nullable(%%)'
        FROM system.columns
        WHERE database = %(database)s
          AND table = %(table)s
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
        if details.table_column == table_column and details.property_name in target_props:
            result.append((col_name, bool(is_nullable)))
    return result


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

        _record_execution_attempt(request, context.run_id)

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


@dagster.op(tags=OWNER_TAG)
def load_hogql_event_removal_request(
    context: dagster.OpExecutionContext,
    config: DataDeletionRequestConfig,
) -> HogQLEventRemovalContext:
    from django.db import transaction

    failure_message: str | None = None
    with transaction.atomic():
        request = (
            DataDeletionRequest.objects.select_for_update()
            .filter(
                pk=config.request_id,
                status=RequestStatus.APPROVED,
                request_type=RequestType.HOGQL_EVENT_REMOVAL,
            )
            .first()
        )

        if request is None:
            raise dagster.Failure(
                f"Request {config.request_id} is not an approved hogql_event_removal request.",
            )
        if request.created_by_id is None:
            request.status = RequestStatus.FAILED
            request.save(update_fields=["status", "updated_at"])
            failure_message = f"Request {config.request_id} has no creator whose query permissions can be enforced."
        else:
            _record_execution_attempt(request, context.run_id)

    if failure_message is not None:
        raise dagster.Failure(failure_message)

    assert request.created_by_id is not None
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "created_by_id": dagster.MetadataValue.int(request.created_by_id),
        }
    )
    return HogQLEventRemovalContext(
        request_id=str(request.pk),
        team_id=request.team_id,
        created_by_id=request.created_by_id,
        query=request.hogql_query,
        variables=request.hogql_variables,
    )


class HogQLEventDeletionExecutor:
    def __init__(self, deletion_request: HogQLEventRemovalContext) -> None:
        self.deletion_request = deletion_request

    def execute(self) -> int:
        from posthog.models import Team, User

        request = self.deletion_request
        try:
            team = Team.objects.get(pk=request.team_id)
            user = User.objects.get(pk=request.created_by_id)
        except (Team.DoesNotExist, User.DoesNotExist) as error:
            raise dagster.Failure("The request team or creator no longer exists.") from error

        try:
            selected = compile_event_uuid_query(
                query=request.query,
                variables=request.variables,
                team=team,
                user=user,
                ch_user=ClickHouseUser.DELETION_EXECUTOR,
            )
        except DjangoValidationError as error:
            raise dagster.Failure(str(error)) from error

        database = django_settings.CLICKHOUSE_DATABASE
        insert_sql = (  # nosemgrep: clickhouse-injection-taint
            f"INSERT INTO {database}.{ADHOC_EVENTS_DELETION_TABLE} "
            "(team_id, uuid, data_deletion_request_id) "
            f"SELECT %(_deletion_team_id)s, selected.*, toUUID(%(_deletion_request_id)s) "
            f"FROM ({selected.sql}) AS selected"
        )
        result = sync_execute(
            insert_sql,
            {
                **selected.context.values,
                "_deletion_team_id": request.team_id,
                "_deletion_request_id": request.request_id,
            },
            workload=Workload.OFFLINE,
            team_id=request.team_id,
            ch_user=ClickHouseUser.DELETION_EXECUTOR,
            settings=selected.settings,
            external_tables=list(selected.context.external_tables.values()) or None,
        )
        return result if isinstance(result, int) else 0


@dagster.op(tags=OWNER_TAG)
def execute_hogql_event_deletion(
    context: dagster.OpExecutionContext,
    deletion_request: HogQLEventRemovalContext,
) -> HogQLEventRemovalContext:
    queued_rows = HogQLEventDeletionExecutor(deletion_request).execute()
    context.add_output_metadata({"queued_rows": dagster.MetadataValue.int(queued_rows)})
    return deletion_request


_HOGQL_UNSWEEPABLE_REASON = (
    "the request carries a HogQL predicate, which only compiles against the events schema "
    "(compile_hogql_predicate resolves every predicate against the events HogQL table, varying only "
    "legacy vs native-JSON, and nothing checks the result against this table's columns). "
    "To proceed, re-file the request without the predicate, or narrow its events to ones this "
    f"table never stores. See {COVERAGE_DOC}."
)


def _refuse_unsweepable(
    cluster: ClickhouseCluster,
    targets: list[DeletionTarget],
    deletion_request: DeletionRequestContext,
    predicate_for: Callable[[DeletionTarget], tuple[str, dict] | NotCounted],
    *,
    reason: str,
    log: logging.Logger | None = None,
) -> None:
    """Raise a dagster.Failure when the request would strand rows on any of ``targets``."""
    try:
        assert_no_unsweepable_rows(
            cluster,
            targets,
            predicate_for,
            events=[] if deletion_request.delete_all_events else deletion_request.events,
            reason=reason,
            log=log,
        )
    except UnsweepableRowsError as exc:
        raise dagster.Failure(description=f"Deletion request {deletion_request.request_id}: {exc}") from exc


_STORES_NONE_OF_THE_PROPERTIES = "the request names only person properties, and this table stores none"


def _deletion_target(data_table: str) -> DeletionTarget:
    return next(target for target in PERSONAL_DATA_TARGETS if target.data_table == data_table)


def _scoped_to(target: DeletionTarget, deletion_request: DeletionRequestContext) -> DeletionRequestContext:
    """The property-removal request narrowed to the property columns ``target`` stores.

    A target without ``stores_person_properties`` (today only flag_evaluations) drops the
    request's ``person_properties`` half, since that column cannot be queried or assigned there;
    see the field's own comment on ``DeletionTarget`` for what that costs.
    """
    return deletion_request if target.stores_person_properties else replace(deletion_request, person_properties=[])


def _names_any_property(request: DeletionRequestContext) -> bool:
    return bool(request.properties or request.person_properties)


def _hogql_excludes(target: DeletionTarget, deletion_request: DeletionRequestContext) -> bool:
    """Whether the request carries a HogQL predicate that does not compile against ``target``."""
    return bool(deletion_request.hogql_predicate) and not target.accepts_hogql_predicate


def _refuse_property_removal_unsweepable(
    cluster: ClickhouseCluster,
    targets: list[DeletionTarget],
    deletion_request: DeletionRequestContext,
    marker_str: str,
    *,
    log: logging.Logger,
) -> None:
    """Gate a property-removal request against every one of ``targets`` the rewrite cannot complete.

    That is a target the job does not rewrite, and a target the request's HogQL predicate excludes,
    which ``_property_rewrite_targets`` leaves out of the sweep.
    """

    def predicate_for(target: DeletionTarget) -> tuple[str, dict] | NotCounted:
        request = _scoped_to(target, deletion_request)
        if not _names_any_property(request):
            return NotCounted(reason=_STORES_NONE_OF_THE_PROPERTIES)
        return _property_removal_where(request, inserted_at_max=marker_str, json_schema=target.uses_new_events_schema)

    _refuse_unsweepable(
        cluster,
        [t for t in targets if not t.accepts_property_rewrite],
        deletion_request,
        predicate_for,
        reason=_PROPERTY_REWRITE_UNSWEEPABLE_REASON,
        log=log,
    )
    _refuse_unsweepable(
        cluster,
        [t for t in targets if t.accepts_property_rewrite and _hogql_excludes(t, deletion_request)],
        deletion_request,
        predicate_for,
        reason=_HOGQL_UNSWEEPABLE_REASON,
        log=log,
    )


def _verify_swept(
    cluster: ClickhouseCluster,
    targets: list[DeletionTarget],
    deletion_request: DeletionRequestContext,
    predicate_for: Callable[[DeletionTarget], tuple[str, dict]],
) -> None:
    """Raise a dagster.Failure when rows this request named are still readable after the sweep."""
    try:
        assert_sweep_complete(
            cluster,
            targets,
            predicate_for,
            events=[] if deletion_request.delete_all_events else deletion_request.events,
        )
    except UnsweptRowsError as exc:
        raise dagster.Failure(description=f"Deletion request {deletion_request.request_id}: {exc}") from exc


def _event_removal_placements(
    cluster: ClickhouseCluster,
    deletion_request: DeletionRequestContext,
    *,
    skip_targets: Collection[DeletionTarget] = (),
) -> list[TargetPlacement]:
    """Targets this event-removal request can sweep, each with the handle that reaches it."""
    events = [] if deletion_request.delete_all_events else deletion_request.events
    # A target that can't hold any of the named events has nothing to sweep, and mutations serialize
    # per table, so enqueueing a no-op one would queue in front of real work.
    # Skipped targets are dropped before resolve_placements, which raises for an unreachable target
    # that still holds rows.
    targets = [t for t in PERSONAL_DATA_TARGETS if t not in skip_targets]
    placements = [p for p in resolve_placements(cluster, targets) if p.target.may_hold_any_of(events)]
    if not deletion_request.hogql_predicate:
        return placements

    unsweepable = [p.target for p in placements if not p.target.accepts_hogql_predicate]
    if unsweepable:
        criteria = portable_event_removal_where(deletion_request)
        _refuse_unsweepable(
            cluster, unsweepable, deletion_request, lambda _target: criteria, reason=_HOGQL_UNSWEEPABLE_REASON
        )
    return [p for p in placements if p.target.accepts_hogql_predicate]


# Immediate deletion leaves flag_evaluations rows to the table's TTL. A HogQL predicate does not
# compile against that table, so gating on it refused every such request whose team had matching
# $feature_flag_called rows. Deferred deletion still queues the table's uuids.
_IMMEDIATE_SKIP_TARGETS = (FLAG_EVALUATIONS,)


@frozen
class EventRemovalShard:
    """One immediate delete: a table, and a shard number on the cluster that carries that table."""

    data_table: str
    shard_num: int


def _placement_for_table(cluster: ClickhouseCluster, data_table: str) -> TargetPlacement:
    target = _deletion_target(data_table)
    placements = resolve_placements(cluster, [target])
    if not placements:
        raise dagster.Failure(description=f"{data_table} is not present on any reachable cluster")
    return placements[0]


def _verify_immediate_event_deletion(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    deletion_request: DeletionRequestContext,
    deleted_shards: list[EventRemovalShard],
) -> None:
    tables = list(dict.fromkeys(shard.data_table for shard in deleted_shards))
    targets = [_deletion_target(table) for table in tables]
    if any(target.uses_patch_parts for target in targets):
        wait_for_patch_part_replication()
    _verify_swept(
        cluster,
        targets,
        deletion_request,
        lambda target: (
            event_removal_where(deletion_request, use_new_events_schema=target.uses_new_events_schema)
            if target.accepts_hogql_predicate
            else portable_event_removal_where(deletion_request)
        ),
    )

    context.add_output_metadata(
        {
            "mode": dagster.MetadataValue.text("immediate"),
            "shards_processed": dagster.MetadataValue.int(len(deleted_shards)),
            "swept_tables": dagster.MetadataValue.text(", ".join(tables)),
        }
    )


def _queue_events_for_deferred_deletion(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    deletion_request: DeletionRequestContext,
) -> None:
    # The queue holds (team_id, uuid) pairs, and the deletes_job drain applies them to every
    # personal-data table. Flag-evaluation rows still have to be read on their own: they mirror a
    # subset of events, so a uuid there may not be in sharded_events once routing moves those
    # events off it.
    placements = [p for p in _event_removal_placements(cluster, deletion_request) if p.target.queue_uuid_candidates]
    # Both halves of the INSERT are host-local: the source table and the queue it feeds. A source
    # on another cluster has no host that holds both, and reading it through its Distributed proxy
    # instead would pull every matching uuid across the wire into one shard's queue.
    stranded = [p.target for p in placements if p.cluster is not cluster]
    if stranded:
        raise dagster.Failure(
            description=(
                f"Deletion request {deletion_request.request_id}: cannot queue uuids from "
                f"{', '.join(t.data_table for t in stranded)}; the queue is on "
                f"{cluster.data_cluster_name!r} and those tables are not. See {COVERAGE_DOC}."
            )
        )
    sources = [p.target for p in placements]
    db = django_settings.CLICKHOUSE_DATABASE
    shards = sorted(cluster.shards)
    predicate, params = event_removal_where(deletion_request)
    params["data_deletion_request_id"] = deletion_request.request_id

    def run_on_shard(client: Client) -> int:
        for source in sources:
            # nosemgrep: clickhouse-fstring-param-audit (all interpolated values are internal constants/settings)
            client.execute(
                f"INSERT INTO {db}.{ADHOC_EVENTS_DELETION_TABLE} (team_id, uuid, data_deletion_request_id) "
                f"SELECT team_id, uuid, toUUID(%(data_deletion_request_id)s) "
                f"FROM {db}.{source.data_table} WHERE {predicate}",
                params,
                settings={"max_execution_time": 1800},
            )
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
        {
            "mode": dagster.MetadataValue.text("deferred"),
            "queued_rows": dagster.MetadataValue.int(total_queued),
            "queued_from": dagster.MetadataValue.text(", ".join(s.data_table for s in sources)),
        }
    )


@dagster.op(out=dagster.DynamicOut(EventRemovalShard), tags=OWNER_TAG)
def get_event_removal_shards(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> Iterator[dagster.DynamicOutput[EventRemovalShard]]:
    """Fan out one delete_event_removal_shard op per table and shard; a deferred request fans out nothing.

    The mapping key makes each delete re-executable on its own from the Dagster UI.
    """
    if deletion_request.execution_mode == ExecutionMode.DEFERRED.value:
        return

    placements = _event_removal_placements(cluster, deletion_request, skip_targets=_IMMEDIATE_SKIP_TARGETS)
    # placement.cluster, not the job's handle: shard numbers are per cluster.
    shards = [
        EventRemovalShard(data_table=placement.target.data_table, shard_num=shard_num)
        for placement in placements
        for shard_num in sorted(placement.cluster.shards)
    ]
    context.log.info(f"Fanning out event removal {deletion_request.request_id} to {len(shards)} shard op(s)")
    for shard in shards:
        yield dagster.DynamicOutput(shard, mapping_key=f"{shard.data_table}_shard_{shard.shard_num}")


@dagster.op(tags=OWNER_TAG, retry_policy=dagster.RetryPolicy(max_retries=0))
def delete_event_removal_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    shard: EventRemovalShard,
    deletion_request: DeletionRequestContext,
) -> EventRemovalShard:
    """Run the lightweight delete for one table on one shard, and wait until it finishes.

    A re-execution waits on the matching mutation in system.mutations if ClickHouse still lists it,
    and enqueues it again otherwise.
    """
    placement = _placement_for_table(cluster, shard.data_table)
    # The HogQL fragment compiles differently per schema: materialized-column/JSONExtract
    # reads on the legacy table, JSON subcolumn reads on the native-JSON table.
    predicate, parameters = event_removal_where(
        deletion_request, use_new_events_schema=placement.target.uses_new_events_schema
    )
    runner = LightweightDeleteMutationRunner(
        table=shard.data_table,
        predicate=predicate,
        parameters=parameters,
        settings={"lightweight_deletes_sync": 0},
        patch_parts=placement.target.uses_patch_parts,
    )

    shard_start = time.monotonic()
    shard_result = placement.cluster.map_any_host_in_shards({shard.shard_num: runner}).result()
    _host, mutation_waiter = next(iter(shard_result.items()))
    placement.cluster.map_all_hosts_in_shard(shard.shard_num, mutation_waiter.wait).result()

    elapsed = time.monotonic() - shard_start
    context.log.info(f"{shard.data_table} shard {shard.shard_num} complete in {elapsed:.1f}s")
    return shard


@dagster.op(tags=OWNER_TAG)
def complete_event_deletion(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
    deleted_shards: list[EventRemovalShard],
) -> DeletionRequestContext:
    """Verify an immediate request after every shard op (a Dagster fan-in), or queue a deferred one."""
    if deletion_request.execution_mode == ExecutionMode.DEFERRED.value:
        _queue_events_for_deferred_deletion(context, cluster, deletion_request)
    else:
        _verify_immediate_event_deletion(context, cluster, deletion_request, deleted_shards)
    return deletion_request


# ---------------------------------------------------------------------------
# Property removal ops
# ---------------------------------------------------------------------------


_PROPERTY_REWRITE_UNSWEEPABLE_REASON = (
    "the property rewrite does not clean every copy of a property this table keeps. The native-JSON "
    "events table also retains temporary properties and quarantine diagnostics, which the rewrite "
    f"leaves in place. See {COVERAGE_DOC}."
)


@dagster.op(tags=OWNER_TAG)
def load_property_removal_request(
    context: dagster.OpExecutionContext,
    config: DataDeletionRequestConfig,
) -> DeletionRequestContext:
    """Load and validate a property removal request, transition to IN_PROGRESS."""
    from django.db import transaction
    from django.utils import timezone

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

        person_properties = list(request.person_properties or [])
        if not request.properties and not person_properties:
            raise dagster.Failure(
                f"Request {config.request_id} has no properties or person_properties specified.",
            )

        _record_execution_attempt(request, context.run_id)

        # Set once and reused verbatim by every retry: all attempts must agree on which
        # inserted_at value identifies cleaned re-inserts, or re-runs duplicate them.
        if request.property_removal_marker is None:
            request.property_removal_marker = timezone.now()
            request.save(update_fields=["property_removal_marker", "updated_at"])

    events_desc = "<all events>" if request.delete_all_events else f"{request.events}"
    context.log.info(
        f"Processing property removal {request.pk}: "
        f"team_id={request.team_id}, events={events_desc}, "
        f"properties={request.properties}, person_properties={person_properties}, "
        f"time_range={request.start_time} to {request.end_time}"
    )
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "events": dagster.MetadataValue.text(
                "<all events>" if request.delete_all_events else ", ".join(request.events)
            ),
            "properties": dagster.MetadataValue.text(", ".join(request.properties)),
            "person_properties": dagster.MetadataValue.text(", ".join(person_properties)),
            "start_time": dagster.MetadataValue.text(str(request.start_time)),
            "end_time": dagster.MetadataValue.text(str(request.end_time)),
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
        properties=request.properties,
        person_properties=person_properties,
        delete_all_events=request.delete_all_events,
        hogql_predicate=request.hogql_predicate or "",
        inserted_at_marker=request.property_removal_marker,
    )


@frozen
class PropertyRemovalTarget:
    """One events table on one shard. Every per-shard property removal op works on one target."""

    table: str
    shard: int
    json_schema: bool

    @property
    def mapping_key(self) -> str:
        return f"{self.table}_shard_{self.shard}"

    @property
    def deletion_target(self) -> DeletionTarget:
        return _deletion_target(self.table)


@frozen
class _ShardStaging:
    """The staged cleaned rows and the progress files of one target, in the data deletion bucket.

    Only ClickHouse reads and writes these objects, through ``s3(...)``. ``data/`` holds one Native
    file of cleaned rows per month. ``state/`` holds one small file per finished step. An op reads
    the progress files first, so a re-executed op, or a new run that the admin Retry button starts,
    skips every step that already finished.
    """

    request_id: str
    target: PropertyRemovalTarget

    @property
    def _base(self) -> str:
        return f"property_removal/{self.request_id}/{self.target.table}/shard_{self.target.shard}"

    def data_args(self, months: list[str] | None = None) -> str:
        """``s3(...)`` arguments for the given monthly files, or for the partitioned write when ``months`` is None."""
        if months is None:
            name = "{_partition_id}"
        elif len(months) == 1:
            name = months[0]
        else:
            name = "{" + ",".join(months) + "}"
        return S3StagingLocation.for_data_deletion().s3_args(f"{self._base}/data/{name}.native", "Native")

    def _state_args(self, step: str) -> str:
        return S3StagingLocation.for_data_deletion().s3_args(
            f"{self._base}/state/{step}.json", "JSONEachRow", _STEP_STRUCTURE
        )

    def finished_steps(self, client: Client) -> dict[str, dict]:
        # A glob that matches no object returns no rows, so a target with no progress yet reads as {}.
        rows = client.execute(f"SELECT step, payload FROM s3({self._state_args('*')})")
        return {step: json.loads(payload) for step, payload in rows}

    def finish_step(self, client: Client, step: str, payload: dict) -> None:
        client.execute(
            f"INSERT INTO FUNCTION s3({self._state_args(step)}) "
            "SELECT %(step)s AS step, %(payload)s AS payload SETTINGS s3_truncate_on_insert=1",
            {"step": step, "payload": json.dumps(payload)},
        )

    def count_staged_uuids(
        self, client: Client, months: list[str], where: str = "1", params: dict | None = None
    ) -> dict[str, int]:
        if not months:
            return {}
        rows = client.execute(
            f"SELECT _file, uniqExact(uuid) FROM s3({self.data_args(months)}) WHERE {where} GROUP BY _file",
            params,
            settings=_LONG_QUERY_SETTINGS,
        )
        return {file.removesuffix(".native"): count for file, count in rows}

    def unexpired_uuids(self, client: Client, months: dict[str, int], where: str, params: dict) -> dict[str, int]:
        """Per month, the staged uuids that a restore check must find back in the table."""
        if self.target.deletion_target.ttl_days is None:
            # The copy and the delete already matched the staged files to these counts.
            return months
        return self.count_staged_uuids(client, sorted(months), where, params)

    def discard_step(self, client: Client, step: str) -> None:
        # ClickHouse cannot delete an S3 object, so the progress file is overwritten with zero rows.
        client.execute(
            f"INSERT INTO FUNCTION s3({self._state_args(step)}) "
            "SELECT '' AS step, '' AS payload WHERE 0 SETTINGS s3_truncate_on_insert=1"
        )

    def empty_data_files(self, client: Client) -> int:
        """Overwrite every staged data file with zero rows, once the target is verified."""
        steps = self.finished_steps(client)
        if _VERIFIED not in steps:
            raise dagster.Failure(description=f"[{self.target.mapping_key}] not verified; keeping the staged copy")
        copied = steps[_COPIED]
        columns = ", ".join(f"`{name}`" for name in copied["columns"])
        for month in sorted(copied["months"]):
            client.execute(
                f"INSERT INTO FUNCTION s3({self.data_args([month])}) "
                f"SELECT {columns} FROM {django_settings.CLICKHOUSE_DATABASE}.{self.target.table} WHERE 0 "
                "SETTINGS s3_truncate_on_insert=1"
            )
        return len(copied["months"])


_STEP_STRUCTURE = "step String, payload String"
_COPIED, _DELETE_STARTED, _DELETED, _REINGESTED, _VERIFIED = (
    "copied",
    "delete_started",
    "deleted",
    "reingested",
    "verified",
)

# Copy and reingest each move a whole request period for one shard in one query, which for a team
# whose every event carries the property is most of that team's data on the shard.
_LONG_QUERY_SETTINGS = {"max_execution_time": 86400}


# The TTL expires a row at the start of a day, so a row this many days short of it has a day left.
_TTL_CHECK_MARGIN_DAYS = 2


def _unexpired_rows(client: Client, target: DeletionTarget) -> tuple[str, dict]:
    """A filter for the rows that the target's TTL cannot drop while a restore check runs.

    With ttl_only_drop_parts, a reingested part that holds only expired rows can drop as soon as it
    lands. The uuids it held then go missing from the count. A part that holds a row this filter
    keeps cannot drop, so every kept row is still there to count. Each call fixes one cutoff, so the
    table side and the staged side of a comparison leave out the same rows.
    """
    if target.ttl_days is None:
        return "1", {}
    [[since]] = client.execute(
        "SELECT toString(now64(6, 'UTC') - toIntervalDay(%(days)s))",
        {"days": target.ttl_days - _TTL_CHECK_MARGIN_DAYS},
    )
    return "timestamp >= toDateTime64(%(unexpired_since)s, 6, 'UTC')", {"unexpired_since": since}


def _datetime64_str(value: datetime) -> str:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _marker_str(deletion_request: DeletionRequestContext) -> str:
    if deletion_request.inserted_at_marker is None:
        raise dagster.Failure(description="property_removal_marker missing; load_property_removal_request must set it")
    # clickhouse-driver serializes a Python datetime with second precision, which truncates the
    # marker. A string with microseconds, cast in SQL, keeps the full precision.
    return _datetime64_str(deletion_request.inserted_at_marker)


def _compile_predicate(deletion_request: DeletionRequestContext, json_schema: bool) -> tuple[str, dict]:
    # HogQL compilation reaches into the Django ORM (Team lookup), so it runs on the op's own thread
    # before the shard work is dispatched to a cluster worker thread. Property access lowers
    # differently on the legacy and native-JSON tables, hence one compilation per schema.
    return compile_hogql_predicate(deletion_request, use_new_events_schema=json_schema)


@frozen
class _ShardPredicate:
    """The removal predicate for one target, built from the materialized columns found on its shard."""

    sql: str
    params: dict
    mat_cols: list[tuple[str, bool]]


def _shard_predicate(
    client: Client,
    deletion_request: DeletionRequestContext,
    target: DeletionTarget,
    marker_str: str,
    hogql_compiled: tuple[str, dict],
    log: QueryLogger | None = None,
) -> _ShardPredicate:
    """Build the predicate that selects this shard's originals.

    Copy, delete and verify all build it here, from the same per-shard materialized column lists and
    the same ``inserted_at < marker`` bound, so they cannot drift. Drift either deletes rows the copy
    does not hold or leaves originals behind.
    """
    # Materialized columns only exist on the legacy table; the JSON table reads properties
    # through JSON subcolumns.
    mat_cols: list[tuple[str, bool]] = []
    person_mat_cols: list[tuple[str, bool]] = []
    if not target.uses_new_events_schema:
        if deletion_request.properties:
            mat_cols = _get_affected_mat_columns(
                client, target.read_table, deletion_request.properties, table_column="properties", log=log
            )
        if deletion_request.person_properties:
            person_mat_cols = _get_affected_mat_columns(
                client, target.read_table, deletion_request.person_properties, table_column="person_properties", log=log
            )
    sql, params = _property_removal_where(
        deletion_request,
        mat_cols=mat_cols,
        person_mat_cols=person_mat_cols,
        inserted_at_max=marker_str,
        hogql_compiled=hogql_compiled,
        json_schema=target.uses_new_events_schema,
    )
    return _ShardPredicate(sql=sql, params=params, mat_cols=mat_cols + person_mat_cols)


def _with_copied_inserted_at_bound(predicate: _ShardPredicate, copied_inserted_at_max: str | None) -> _ShardPredicate:
    params = dict(predicate.params)
    if copied_inserted_at_max is None:
        inserted_at_sql = "inserted_at IS NULL"
    else:
        inserted_at_sql = "(inserted_at IS NULL OR inserted_at <= toDateTime64(%(copied_inserted_at_max)s, 6, 'UTC'))"
        params["copied_inserted_at_max"] = copied_inserted_at_max
    return _ShardPredicate(
        sql=f"{predicate.sql} AND {inserted_at_sql}",
        params=params,
        mat_cols=predicate.mat_cols,
    )


@frozen
class _CleanedSelect:
    """How the copy reads cleaned rows out of the source table."""

    # The source columns in table order. The reingest inserts the staged files into exactly these.
    columns: list[str]
    # One SELECT expression per column, in the same order.
    expressions: list[str]
    params: dict


def _cleaned_select_list(
    client: Client,
    deletion_request: DeletionRequestContext,
    target: PropertyRemovalTarget,
    mat_cols: list[tuple[str, bool]],
    marker_str: str,
) -> _CleanedSelect:
    """The column names and SELECT expressions that copy cleaned rows out of the source table.

    The columns are the ``SELECT *`` shape of the table, so MATERIALIZED columns are left out and the
    reingest recomputes them. Each replaced value is cast back to its column type, so the Native file
    holds exactly the types the reingest inserts.
    """
    rows = client.execute(
        "SELECT name, type FROM system.columns WHERE database = %(db)s AND table = %(table)s "
        "AND default_kind NOT IN ('MATERIALIZED', 'ALIAS', 'EPHEMERAL') ORDER BY position",
        {"db": django_settings.CLICKHOUSE_DATABASE, "table": target.table},
    )
    [[engine]] = client.execute(
        "SELECT engine FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": django_settings.CLICKHOUSE_DATABASE, "table": target.table},
    )
    params: dict = {"inserted_at_marker": marker_str}
    replacements: dict[str, str] = {"inserted_at": "toDateTime64(%(inserted_at_marker)s, 6, 'UTC')"}
    # Bump the ReplacingMergeTree version (ver=_timestamp) past the original's, so a merge that
    # meets a cleaned row and an original with the same sorting key keeps the cleaned row. +1
    # second because _timestamp is second-precision while the marker is microsecond-precision.
    # A plain MergeTree such as flag_evaluations keeps the original value, because there _timestamp
    # is the Kafka message time that flag_evaluations_backfill reads as the consumer position.
    if "ReplacingMergeTree" in engine:
        replacements["_timestamp"] = "toDateTime(toDateTime64(%(inserted_at_marker)s, 6, 'UTC')) + 1"
    # On the JSON table the column round-trips through a string: serialize it, drop the keys, and
    # let the cast below turn the cleaned string back into the JSON column type.
    if deletion_request.properties:
        source = "toJSONString(properties)" if target.json_schema else "properties"
        replacements["properties"] = f"JSONDropKeysPool({source}, %(keys)s)"
        params["keys"] = deletion_request.properties
    if deletion_request.person_properties:
        source = "toJSONString(person_properties)" if target.json_schema else "person_properties"
        replacements["person_properties"] = f"JSONDropKeysPool({source}, %(person_keys)s)"
        params["person_keys"] = deletion_request.person_properties
    for name, is_nullable in mat_cols:
        replacements[name] = "NULL" if is_nullable else "''"

    return _CleanedSelect(
        columns=[name for name, _ in rows],
        expressions=[
            f"CAST({replacements[name]} AS {col_type}) AS `{name}`" if name in replacements else f"`{name}`"
            for name, col_type in rows
        ],
        params=params,
    )


def _sync_replica(client: Client, target: PropertyRemovalTarget, log: QueryLogger) -> None:
    """Fetch every part other replicas of this shard hold before the next read.

    The delete is a replicated mutation, so it removes matching rows on every replica. A host that has
    not fetched a part inserted elsewhere would copy and count without those rows, and the delete would
    then remove rows no copy holds. LIGHTWEIGHT waits only for part fetches already queued, not for
    merges, so it stays bounded on a table that keeps ingesting.
    """
    sql = f"SYSTEM SYNC REPLICA {django_settings.CLICKHOUSE_DATABASE}.{target.table} LIGHTWEIGHT"
    log("sync-replica", sql)
    client.execute(sql)


def _run_on_shard(cluster: ClickhouseCluster, target: PropertyRemovalTarget, fn: Callable[[Client], T]) -> T:
    """Run ``fn`` on one host of the target's shard and return its result."""
    try:
        result = cluster.map_any_host_in_shards({target.shard: fn}).result()
    except ExceptionGroup as group:
        # Only one host runs, so raise its error directly. A dagster.Failure then keeps its
        # description in the Dagster UI instead of hiding inside an exception group.
        if len(group.exceptions) == 1:
            raise group.exceptions[0] from group
        raise
    return next(iter(result.values()))


def _cluster_for(cluster: ClickhouseCluster, target: PropertyRemovalTarget) -> ClickhouseCluster:
    """The handle whose shards carry ``target``'s table, which for sharded_events_json is the events cluster."""
    placement = placement_for(cluster, target.deletion_target)
    if placement is None:
        raise dagster.Failure(description=f"{target.table} is not present on any reachable cluster")
    return placement.cluster


def _query_logger(context: dagster.OpExecutionContext, target: PropertyRemovalTarget) -> QueryLogger:
    def log(label: str, sql: str) -> None:
        context.log.info(f"[{target.mapping_key}] [{label}] {' '.join(sql.split())}")

    return log


def _property_rewrite_targets(
    targets: list[DeletionTarget], deletion_request: DeletionRequestContext, *, log: logging.Logger
) -> list[DeletionTarget]:
    """The tables out of ``targets`` that this request's sweep rewrites and its verification counts.

    A target the request's HogQL predicate excludes is left out, and
    ``_refuse_property_removal_unsweepable`` refuses the request while such a target holds rows the
    request names.
    """
    events = [] if deletion_request.delete_all_events else deletion_request.events
    swept: list[DeletionTarget] = []
    for target in targets:
        if not target.accepts_property_rewrite or _hogql_excludes(target, deletion_request):
            continue
        if not target.may_hold_any_of(events):
            log.info(f"{target.read_table}: not rewritten, because it stores none of the request's events")
            continue
        if not _names_any_property(_scoped_to(target, deletion_request)):
            log.info(f"{target.read_table}: not rewritten, because {_STORES_NONE_OF_THE_PROPERTIES}")
            continue
        swept.append(target)
    return swept


@dagster.op(out=dagster.DynamicOut(PropertyRemovalTarget), tags=OWNER_TAG)
def get_property_removal_shards(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
):
    """Fan out one chain of per-shard ops for each events table on each shard.

    Takes the deletion request as input so fan-out is sequenced after the load op; the mapping key
    makes each step of each shard re-executable individually from the Dagster UI.

    Also the gate for targets this job cannot rewrite: refusing here, before any shard mutates
    anything, is what stops the request completing while matching rows survive elsewhere. It lives
    in this op rather than the load op because this is the first one holding a cluster handle.
    """
    placements = resolve_placements(cluster)
    # Bound by the same marker as the sweep and the verify gate, so a row ingested after the
    # marker, which the sweep would never touch, cannot refuse the request forever.
    _refuse_property_removal_unsweepable(
        cluster, [p.target for p in placements], deletion_request, _marker_str(deletion_request), log=context.log
    )

    swept = _property_rewrite_targets([p.target for p in placements], deletion_request, log=context.log)
    rewritten = [p for p in placements if p.target in swept]
    context.log.info(
        f"Fanning out property removal {deletion_request.request_id} to "
        + ", ".join(f"{p.target.data_table} x {len(p.cluster.shards)} shard(s)" for p in rewritten)
    )
    for placement in rewritten:
        for shard in sorted(placement.cluster.shards):
            target = PropertyRemovalTarget(
                table=placement.target.data_table, shard=shard, json_schema=placement.target.uses_new_events_schema
            )
            yield dagster.DynamicOutput(target, mapping_key=target.mapping_key)


def _copy_property_removal_target(
    client: Client,
    deletion_request: DeletionRequestContext,
    target: PropertyRemovalTarget,
    marker_str: str,
    hogql_compiled: tuple[str, dict],
    staging: _ShardStaging,
    log: QueryLogger,
) -> dict:
    db = django_settings.CLICKHOUSE_DATABASE
    steps = staging.finished_steps(client)
    if _COPIED in steps:
        log("skip", "copy already finished")
        return steps[_COPIED]
    if _DELETE_STARTED in steps:
        # A delete may have removed originals already, so the staged files are their only copy.
        # Copying again would overwrite them with the survivors.
        raise dagster.Failure(
            description=f"[{target.mapping_key}] a delete started without a finished copy; refusing to copy "
            "again over the only copy of the deleted rows. Investigate."
        )

    _sync_replica(client, target, log)
    predicate = _shard_predicate(client, deletion_request, target.deletion_target, marker_str, hogql_compiled, log)
    inserted_at_sql = f"SELECT maxOrNull(inserted_at) FROM {db}.{target.table} WHERE {predicate.sql}"
    log("max-inserted-at", inserted_at_sql)
    [[inserted_at_max]] = client.execute(inserted_at_sql, predicate.params, settings=_LONG_QUERY_SETTINGS)
    copied_inserted_at_max = _datetime64_str(inserted_at_max) if inserted_at_max is not None else None
    predicate = _with_copied_inserted_at_bound(predicate, copied_inserted_at_max)
    cleaned = _cleaned_select_list(client, deletion_request, target, predicate.mat_cols, marker_str)

    count_sql = (
        f"SELECT toString(toYYYYMM(timestamp)) AS month, uniqExact(uuid) FROM {db}.{target.table} "
        f"WHERE {predicate.sql} GROUP BY month"
    )
    log("count-originals", count_sql)
    months = dict(client.execute(count_sql, predicate.params, settings=_LONG_QUERY_SETTINGS))

    if months:
        # The predicate filters in an inner query. ClickHouse resolves a SELECT alias inside the
        # WHERE of the same query, so a cleaned `properties` alias would hide the original column
        # from the presence check and the copy would match nothing.
        copy_sql = (
            f"INSERT INTO FUNCTION s3({staging.data_args()}) PARTITION BY toYYYYMM(timestamp) "
            f"SELECT {', '.join(cleaned.expressions)} FROM (SELECT * FROM {db}.{target.table} WHERE {predicate.sql})"
        )
        log("copy-to-s3", copy_sql)
        client.execute(
            copy_sql,
            {**predicate.params, **cleaned.params},
            settings={**_LONG_QUERY_SETTINGS, "s3_truncate_on_insert": 1},
        )

    staged = staging.count_staged_uuids(client, sorted(months))
    if staged != months:
        raise dagster.Failure(
            description=f"[{target.mapping_key}] staged copy does not match the originals: "
            f"source={months}, staged={staged}. Re-execute this step."
        )
    residual_sql = (
        f"SELECT count() FROM s3({staging.data_args(sorted(months))}) "
        f"WHERE {_target_presence_clause(deletion_request, target, predicate.mat_cols)}"
    )
    if months and client.execute(residual_sql, _presence_params(deletion_request))[0][0]:
        raise dagster.Failure(description=f"[{target.mapping_key}] staged copy still carries target properties")

    payload = {
        "rows": sum(months.values()),
        "months": months,
        "columns": cleaned.columns,
        "inserted_at_max": copied_inserted_at_max,
    }
    staging.finish_step(client, _COPIED, payload)
    return payload


@dagster.op(tags=OWNER_TAG, retry_policy=dagster.RetryPolicy(max_retries=0))
def copy_property_removal_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    target: PropertyRemovalTarget,
    deletion_request: DeletionRequestContext,
) -> PropertyRemovalTarget:
    """Copy the shard's matching originals to S3 with the properties already dropped.

    One query covers the whole request period and writes one Native file per month. The rows are
    cleaned on the way out, so the staged copy never holds the removed values, and the reingest
    inserts it unchanged. Re-running before the delete step is safe: the originals are still in
    ClickHouse, and the write overwrites each monthly file.
    """
    marker_str = _marker_str(deletion_request)
    hogql_compiled = _compile_predicate(deletion_request, target.json_schema)
    request = _scoped_to(target.deletion_target, deletion_request)
    staging = _ShardStaging(request_id=deletion_request.request_id, target=target)
    log = _query_logger(context, target)

    def copy(client: Client) -> dict:
        return _copy_property_removal_target(client, request, target, marker_str, hogql_compiled, staging, log)

    copied = _run_on_shard(_cluster_for(cluster, target), target, copy)
    context.add_output_metadata({"copied": dagster.MetadataValue.int(copied["rows"])})
    return target


@dagster.op(tags=OWNER_TAG, retry_policy=dagster.RetryPolicy(max_retries=0))
def delete_property_removal_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    target: PropertyRemovalTarget,
    deletion_request: DeletionRequestContext,
) -> PropertyRemovalTarget:
    """Delete the shard's originals once the staged copy is confirmed to hold every one of them.

    From here until the reingest finishes, the staged copy is the only copy of these rows.
    """
    db = django_settings.CLICKHOUSE_DATABASE
    marker_str = _marker_str(deletion_request)
    hogql_compiled = _compile_predicate(deletion_request, target.json_schema)
    request = _scoped_to(target.deletion_target, deletion_request)
    staging = _ShardStaging(request_id=deletion_request.request_id, target=target)
    log = _query_logger(context, target)

    def delete(client: Client) -> int:
        steps = staging.finished_steps(client)
        if _DELETED in steps:
            log("skip", "delete already finished")
            return steps[_DELETED]["rows"]
        if _COPIED not in steps:
            raise dagster.Failure(
                description=f"[{target.mapping_key}] staged copy is missing. Re-execute the copy step before "
                "the delete step. Nothing was deleted."
            )
        copied = steps[_COPIED]

        staged = staging.count_staged_uuids(client, sorted(copied["months"]))
        if staged != copied["months"]:
            raise dagster.Failure(
                description=f"[{target.mapping_key}] staged copy changed since the copy step: "
                f"expected={copied['months']}, staged={staged}. Do not delete; investigate."
            )

        _sync_replica(client, target, log)
        predicate = _shard_predicate(client, request, target.deletion_target, marker_str, hogql_compiled, log)
        predicate = _with_copied_inserted_at_bound(predicate, copied["inserted_at_max"])
        count_sql = (
            f"SELECT toString(toYYYYMM(timestamp)) AS month, uniqExact(uuid) "
            f"FROM {db}.{target.table} WHERE {predicate.sql} GROUP BY month"
        )
        log("count-originals", count_sql)
        source = dict(client.execute(count_sql, predicate.params, settings=_LONG_QUERY_SETTINGS))
        originals = sum(source.values())
        if source != staged:
            if _DELETE_STARTED not in steps:
                # Nothing is deleted yet, so copying again is safe. Discarding the copy's progress file
                # lets a re-execution of this delete step rebuild it from the current source.
                staging.discard_step(client, _COPIED)
                raise dagster.Failure(
                    description=f"[{target.mapping_key}] original counts differ from the staged copy "
                    f"(source={source}, staged={staged}). Nothing was deleted. Re-execute this step to rebuild "
                    "the copy and retry."
                )
            # An earlier attempt started the delete and may have removed some originals, so the staged
            # files are the only copy of those and must stay. The survivors only have to be a subset of
            # the staged rows. The join hashes the survivors, the smaller side, and streams the files.
            unstaged_sql = (
                f"SELECT count() FROM s3({staging.data_args(sorted(copied['months']))}) AS staged "
                f"RIGHT ANTI JOIN (SELECT uuid FROM {db}.{target.table} WHERE {predicate.sql}) AS source "
                "USING (uuid)"
            )
            unstaged = (
                client.execute(unstaged_sql, predicate.params, settings=_LONG_QUERY_SETTINGS)[0][0]
                if copied["months"]
                else originals
            )
            if unstaged:
                raise dagster.Failure(
                    description=f"[{target.mapping_key}] {unstaged} originals are not in the staged copy, and an "
                    "earlier attempt already started deleting. The staged copy is kept. Investigate before "
                    "re-running."
                )
        elif _DELETE_STARTED not in steps:
            # Recorded before the mutation is enqueued. From here on the copy is never discarded, because
            # the delete may remove rows whose only other copy is staged.
            staging.finish_step(client, _DELETE_STARTED, {"rows": originals})

        if originals:
            # The server clock dates the cutoff, as it dates the mutations. A retry then enqueues its own
            # delete instead of adopting an earlier attempt's, which may have been killed part way.
            [[delete_since]] = client.execute("SELECT now()")
            delete_runner = LightweightDeleteMutationRunner(
                table=target.table,
                predicate=predicate.sql,
                parameters=predicate.params,
                settings={"lightweight_deletes_sync": 2, "mutations_sync": 2},
                reuse_since=delete_since,
                patch_parts=target.deletion_target.uses_patch_parts,
            )
            log("delete-originals", delete_runner.get_statement(delete_runner.get_all_commands()))
            # mutations_sync = 2 blocks on every replica of this shard; the explicit wait is a backstop.
            delete_runner(client).wait(client)

        staging.finish_step(client, _DELETED, {"rows": originals})
        return originals

    deleted = _run_on_shard(_cluster_for(cluster, target), target, delete)
    context.add_output_metadata({"deleted": dagster.MetadataValue.int(deleted)})
    return target


@dagster.op(tags=OWNER_TAG, retry_policy=dagster.RetryPolicy(max_retries=0))
def reingest_property_removal_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    target: PropertyRemovalTarget,
    deletion_request: DeletionRequestContext,
) -> PropertyRemovalTarget:
    """Insert the staged cleaned rows back into the shard, one monthly file at a time.

    Each month gets its own progress file, so a retry repeats only the month that failed.
    """
    db = django_settings.CLICKHOUSE_DATABASE
    marker_str = _marker_str(deletion_request)
    staging = _ShardStaging(request_id=deletion_request.request_id, target=target)
    log = _query_logger(context, target)
    params = {
        "team_id": deletion_request.team_id,
        "start_time": deletion_request.start_time,
        "end_time": deletion_request.end_time,
        "marker": marker_str,
    }

    def reingest(client: Client) -> int:
        steps = staging.finished_steps(client)
        if _REINGESTED in steps:
            log("skip", "reingest already finished")
            return steps[_REINGESTED]["rows"]
        if _DELETED not in steps:
            raise dagster.Failure(description=f"[{target.mapping_key}] delete has not finished; refusing to reingest")
        copied = steps[_COPIED]
        columns = ", ".join(f"`{name}`" for name in copied["columns"])

        # A failed earlier attempt may have inserted a month on another replica of this shard. Without
        # that part here, the leftover count below misses those rows and the insert adds them a second
        # time, which a plain MergeTree such as flag_evaluations never merges away.
        _sync_replica(client, target, log)
        for month, expected in sorted(copied["months"].items()):
            if f"{_REINGESTED}_{month}" in steps:
                continue
            month_params = {**params, "month": int(month)}
            cleaned_rows = (
                "team_id = %(team_id)s AND timestamp >= %(start_time)s AND timestamp < %(end_time)s "
                "AND toYYYYMM(timestamp) = %(month)s AND inserted_at = toDateTime64(%(marker)s, 6, 'UTC')"
            )
            # A failed earlier attempt may have inserted part of this month. Only rows whose uuid is in
            # the file are cleared, so every row removed here comes back with the insert below.
            partial_rows = f"{cleaned_rows} AND uuid IN (SELECT uuid FROM s3({staging.data_args([month])}))"
            leftovers = client.execute(
                f"SELECT count() FROM {db}.{target.table} WHERE {partial_rows}",
                month_params,
                settings=_LONG_QUERY_SETTINGS,
            )[0][0]
            if leftovers:
                # Every attempt renders the same command for a month, so a runner left to adopt existing
                # mutations would reuse an earlier attempt's finished clear and skip the rows the last
                # failed insert added. The server clock dates the cutoff, as it dates the mutations.
                [[clear_since]] = client.execute("SELECT now()")
                clear_runner = LightweightDeleteMutationRunner(
                    table=target.table,
                    predicate=partial_rows,
                    parameters=month_params,
                    settings={"lightweight_deletes_sync": 2, "mutations_sync": 2},
                    reuse_since=clear_since,
                    patch_parts=target.deletion_target.uses_patch_parts,
                )
                log("clear-partial-reingest", clear_runner.get_statement(clear_runner.get_all_commands()))
                clear_runner(client).wait(client)

            insert_sql = (
                f"INSERT INTO {db}.{target.table} ({columns}) SELECT {columns} FROM s3({staging.data_args([month])})"
            )
            log("reingest-month", insert_sql)
            # Replicated tables drop a block whose hash matches a recent insert. A retry re-inserts the
            # same blocks, so deduplication would silently drop the rows this month needs.
            client.execute(insert_sql, settings={**_LONG_QUERY_SETTINGS, "insert_deduplicate": 0})

            unexpired_sql, unexpired_params = _unexpired_rows(client, target.deletion_target)
            expected = staging.unexpired_uuids(client, {month: expected}, unexpired_sql, unexpired_params).get(month, 0)
            stamped = client.execute(
                f"SELECT uniqExact(uuid) FROM {db}.{target.table} WHERE {partial_rows} AND {unexpired_sql}",
                {**month_params, **unexpired_params},
                settings=_LONG_QUERY_SETTINGS,
            )[0][0]
            if stamped != expected:
                raise dagster.Failure(
                    description=f"[{target.mapping_key}] month {month}: {stamped} cleaned uuids present, "
                    f"{expected} staged. Re-execute this step."
                )
            staging.finish_step(client, f"{_REINGESTED}_{month}", {"rows": stamped})

        staging.finish_step(client, _REINGESTED, {"rows": copied["rows"]})
        return copied["rows"]

    reingested = _run_on_shard(_cluster_for(cluster, target), target, reingest)
    context.add_output_metadata({"reingested": dagster.MetadataValue.int(reingested)})
    return target


@dagster.op(tags=OWNER_TAG, retry_policy=dagster.RetryPolicy(max_retries=0))
def verify_property_removal_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    target: PropertyRemovalTarget,
    deletion_request: DeletionRequestContext,
) -> dict:
    """Fail when this shard kept an original, lost a uuid, or holds a target property on a cleaned row."""
    db = django_settings.CLICKHOUSE_DATABASE
    marker_str = _marker_str(deletion_request)
    hogql_compiled = _compile_predicate(deletion_request, target.json_schema)
    request = _scoped_to(target.deletion_target, deletion_request)
    staging = _ShardStaging(request_id=deletion_request.request_id, target=target)
    log = _query_logger(context, target)

    def verify(client: Client) -> dict:
        steps = staging.finished_steps(client)
        if _REINGESTED not in steps:
            raise dagster.Failure(description=f"[{target.mapping_key}] reingest has not finished; nothing to verify")
        copied = steps[_COPIED]
        stats = {
            "table": target.table,
            "shard": target.shard,
            "json_schema": target.json_schema,
            "copied": copied["rows"],
        }
        if _VERIFIED in steps:
            log("skip", "verify already finished")
            return stats

        _sync_replica(client, target, log)
        predicate = _shard_predicate(client, request, target.deletion_target, marker_str, hogql_compiled, log)
        predicate = _with_copied_inserted_at_bound(predicate, copied["inserted_at_max"])
        remaining = client.execute(
            f"SELECT count() FROM {db}.{target.table} WHERE {predicate.sql}",
            predicate.params,
            settings=_LONG_QUERY_SETTINGS,
        )[0][0]
        cleaned_rows = (
            "team_id = %(team_id)s AND timestamp >= %(start_time)s AND timestamp < %(end_time)s "
            "AND inserted_at = toDateTime64(%(marker)s, 6, 'UTC')"
        )
        cleaned_params = {
            "team_id": deletion_request.team_id,
            "start_time": deletion_request.start_time,
            "end_time": deletion_request.end_time,
            "marker": marker_str,
            **_presence_params(request),
        }
        presence = _target_presence_clause(request, target, predicate.mat_cols)
        unexpired_sql, unexpired_params = _unexpired_rows(client, target.deletion_target)
        expected_months = staging.unexpired_uuids(client, copied["months"], unexpired_sql, unexpired_params)
        cleaned_stats = client.execute(
            f"SELECT toString(toYYYYMM(timestamp)) AS month, uniqExactIf(uuid, {unexpired_sql}), countIf({presence}) "
            f"FROM {db}.{target.table} WHERE {cleaned_rows} GROUP BY month",
            {**cleaned_params, **unexpired_params},
            settings=_LONG_QUERY_SETTINGS,
        )
        cleaned_months = {month: count for month, count, _ in cleaned_stats if count}
        still_present = sum(present for _, _, present in cleaned_stats)
        if remaining or still_present or cleaned_months != expected_months:
            raise dagster.Failure(
                description=f"[{target.mapping_key}] verification failed: {remaining} originals remain, "
                f"cleaned={cleaned_months}, expected={expected_months}, {still_present} cleaned rows still carry "
                "a target property. Investigate before re-running."
            )
        staging.finish_step(client, _VERIFIED, {"rows": sum(cleaned_months.values())})
        return stats

    stats = _run_on_shard(_cluster_for(cluster, target), target, verify)
    context.add_output_metadata({"verified": dagster.MetadataValue.int(stats["copied"])})
    return stats


def _target_presence_clause(
    deletion_request: DeletionRequestContext, target: PropertyRemovalTarget, mat_cols: list[tuple[str, bool]]
) -> str:
    """True for a row that still carries any target property, in JSON or in a materialized column."""
    clauses: list[str] = []
    if deletion_request.properties:
        clauses.append(
            _json_property_filter_clause(deletion_request.properties, column="properties")
            if target.json_schema
            else _property_filter_clause(deletion_request.properties)
        )
    elif target.json_schema and deletion_request.person_properties:
        # Matches the selection in _property_removal_where: quarantined raw properties can hold a
        # $set copy of a person property, and the copy does not clean them.
        clauses.append(json_property_presence_expr("properties", UNPARSEABLE_PROPERTIES_KEY))
    if deletion_request.person_properties:
        clauses.append(
            _json_property_filter_clause(deletion_request.person_properties, column="person_properties")
            if target.json_schema
            else _property_filter_clause(deletion_request.person_properties, prefix="pp_", column="person_properties")
        )
    clauses.extend(_mat_col_presence_clauses(mat_cols))
    return f"({' OR '.join(clauses)})"


def _presence_params(deletion_request: DeletionRequestContext) -> dict:
    params = _property_filter_params(deletion_request.properties)
    if deletion_request.person_properties:
        params.update(_property_filter_params(deletion_request.person_properties, prefix="pp_"))
    return params


@dagster.op(tags=OWNER_TAG)
def verify_property_removal(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
    shard_stats: list[dict],
) -> DeletionRequestContext:
    """Fail the run when property removal left originals behind.

    Takes ``shard_stats`` (one dict per shard op) purely to sequence verification after every
    shard op has finished — a Dagster fan-in.

    Checks the Distributed read table of every table the sweep rewrote for rows that still match
    the full removal predicate. It uses the same ``inserted_at_max`` bound as the copy and delete
    passes, so post-marker ingestion cannot wedge verification. A non-zero result means an original
    survived.
    """
    total_copied = sum(stats["copied"] for stats in shard_stats)
    context.log.info(f"All {len(shard_stats)} shard op(s) finished; {total_copied} events copied+cleaned in total")
    marker_str = _marker_str(deletion_request)

    # Repeat the fan-out gate here. That one is point-in-time: rows can land between it and now, and
    # a re-execution from a failed shard reuses the fan-out op's cached output without re-running it.
    # Bounded by the same marker as the checks below so post-marker ingestion can't wedge the run.
    placements = resolve_placements(cluster)
    _refuse_property_removal_unsweepable(
        cluster, [p.target for p in placements], deletion_request, marker_str, log=context.log
    )

    def check(client: Client, target: DeletionTarget, hogql_compiled: tuple[str, dict]) -> int:
        request = _scoped_to(target, deletion_request)
        predicate = _shard_predicate(client, request, target, marker_str, hogql_compiled)
        return client.execute(
            surviving_rows_sql(target.read_table, predicate.sql),
            predicate.params,
            settings={"max_execution_time": 1800},
        )[0][0]

    swept = _property_rewrite_targets([p.target for p in placements], deletion_request, log=context.log)
    if any(target.uses_patch_parts for target in swept):
        wait_for_patch_part_replication()
    pending = [
        cluster.any_host_by_role(
            partial(
                check,
                target=target,
                hogql_compiled=_compile_predicate(deletion_request, target.uses_new_events_schema),
            ),
            NodeRole.DATA,
        )
        for target in swept
    ]
    remaining = sum(future.result() for future in pending)
    context.add_output_metadata(
        {
            "remaining_originals": dagster.MetadataValue.int(remaining),
            "shards_processed": dagster.MetadataValue.int(len(shard_stats)),
            "total_copied": dagster.MetadataValue.int(total_copied),
        }
    )
    if remaining:
        raise dagster.Failure(
            description=(
                f"Property removal verification failed for request {deletion_request.request_id}: "
                f"{remaining} events still match the removal predicate. Investigate before re-approving."
            )
        )
    context.log.info("Property removal verified: no residual originals.")
    return deletion_request


@dagster.op(tags=OWNER_TAG)
def cleanup_property_removal_staging(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
    shard_stats: list[dict],
) -> DeletionRequestContext:
    """Empty every staged data file once the whole request is verified.

    ClickHouse cannot delete an S3 object, so each monthly file is overwritten with zero rows. The
    bucket lifecycle rule removes the files later. The progress files stay until then, so a later
    retry of this request skips every step instead of copying again.
    """
    for stats in shard_stats:
        target = PropertyRemovalTarget(table=stats["table"], shard=stats["shard"], json_schema=stats["json_schema"])
        staging = _ShardStaging(request_id=deletion_request.request_id, target=target)

        emptied = _run_on_shard(_cluster_for(cluster, target), target, staging.empty_data_files)
        context.log.info(f"[{target.mapping_key}] emptied {emptied} staged file(s)")
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

        _record_execution_attempt(request, context.run_id)

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
    """Build WHERE predicate + params for rows linked to the targeted persons.

    Keyed on ``person_id`` only, like every other events-shaped deletion. The producers of these
    tables populate ``person_id`` for every row (the resolved uuid, else a deterministic
    per-distinct_id uuid), so a distinct_id arm would only widen the match to rows the person
    already owns.
    """
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
    """Per-shard lightweight delete of person-linked rows on every personal-data table."""
    if not person_removal.drop_events:
        context.log.info("drop_events=False, skipping event deletion")
        return person_removal

    # The tables are keyed by person_id (UUID), so resolve distinct_ids → uuids when the request was
    # submitted by distinct_id. Selectors are mutually exclusive (enforced in
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

    placements = resolve_placements(cluster)
    targets = [p.target for p in placements]
    context.log.info(
        f"Deleting rows for {len(person_removal.person_uuids)} persons on tables {[t.data_table for t in targets]}"
    )

    # Schema-agnostic columns only (team_id, person_id, timestamp), so one predicate serves every
    # target.
    predicate, params = _person_event_predicate(person_removal)
    swept_shards = 0
    for placement in placements:
        target = placement.target
        # placement.cluster, not the job's handle: shard numbers are per cluster.
        shards = sorted(placement.cluster.shards)
        swept_shards += len(shards)
        for idx, shard_num in enumerate(shards, 1):
            context.log.info(f"Processing {target.data_table} shard {shard_num} ({idx}/{len(shards)})")
            shard_start = time.monotonic()
            runner = LightweightDeleteMutationRunner(
                table=target.data_table,
                predicate=predicate,
                parameters=params,
                settings={"lightweight_deletes_sync": 0},
                patch_parts=target.uses_patch_parts,
            )
            shard_result = placement.cluster.map_any_host_in_shards({shard_num: runner}).result()
            _host, waiter = next(iter(shard_result.items()))
            placement.cluster.map_all_hosts_in_shard(shard_num, waiter.wait).result()
            context.log.info(f"{target.data_table} shard {shard_num} complete in {time.monotonic() - shard_start:.1f}s")

    if any(target.uses_patch_parts for target in targets):
        wait_for_patch_part_replication()
    try:
        assert_sweep_complete(cluster, targets, lambda _target: (predicate, params), events=[])
    except UnsweptRowsError as exc:
        raise dagster.Failure(description=f"Deletion request {person_removal.request_id}: {exc}") from exc

    context.add_output_metadata(
        {
            "shards_processed": dagster.MetadataValue.int(swept_shards),
            "swept_tables": dagster.MetadataValue.text(", ".join(t.data_table for t in targets)),
        }
    )
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
    """Tombstone Person rows in Postgres and publish the ClickHouse tombstones, last.

    On per-person failures, errors are recorded in op metadata and the request is allowed to
    transition to COMPLETED — Postgres rows remain for the failed UUIDs and the operator can
    submit a follow-up request for them. This mirrors the best-effort semantics of the
    `POST /api/projects/:id/persons/bulk_delete/` endpoint and avoids flipping the whole
    request to FAILED after upstream events/recordings ops have already done their work.

    Receipt preparation and the Postgres tombstone keep profiles live when they fail,
    so the op raises and the request finalizes as FAILED for a retry. A failed
    ClickHouse publish after a Postgres tombstone does not raise, because the person is deleted
    and the weekly deletion sweep republishes it.
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
        context.log.warning(f"Person profile deletion had {len(result.errors)} per-person failures")
        metadata["error_uuids"] = dagster.MetadataValue.text(", ".join(str(u) for u in result.errors))
    blocking_failures = [
        failure
        for failure in result.failures
        if failure.step in (PersonDeletionStep.TOMBSTONE_POSTGRES, PersonDeletionStep.QUEUE_MEMBERSHIP_DELETION)
    ]
    if blocking_failures:
        step = (
            "receipt preparation"
            if blocking_failures[0].step == PersonDeletionStep.QUEUE_MEMBERSHIP_DELETION
            else "Postgres tombstone"
        )
        raise dagster.Failure(
            description=(
                f"Deletion request {person_removal.request_id}: {step} failed for "
                f"{len(blocking_failures)} persons ({blocking_failures[0].error}). Retry the request."
            ),
            metadata=metadata,
        )
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

    # Accept FAILED in addition to IN_PROGRESS: when an op fails the failure hook flips the request
    # to FAILED, so re-running the job from the failed op in Dagster (where load_* is reused and not
    # re-executed) leaves it FAILED. Allowing FAILED here lets that re-run finalize the request.
    DataDeletionRequest.objects.filter(
        pk=deletion_request.request_id,
        status__in=[RequestStatus.IN_PROGRESS, RequestStatus.FAILED],
    ).update(status=next_status, updated_at=timezone.now())

    context.log.info(f"Deletion request {deletion_request.request_id} marked as {next_status.value}.")


@dagster.op(tags=OWNER_TAG)
def finalize_hogql_event_removal(
    context: dagster.OpExecutionContext,
    deletion_request: HogQLEventRemovalContext,
) -> None:
    from django.utils import timezone

    DataDeletionRequest.objects.filter(
        pk=deletion_request.request_id,
        status__in=[RequestStatus.IN_PROGRESS, RequestStatus.FAILED],
    ).update(status=RequestStatus.QUEUED, updated_at=timezone.now())

    context.log.info(f"Deletion request {deletion_request.request_id} marked as queued.")


@dagster.op(tags=OWNER_TAG)
def finalize_person_removal(
    context: dagster.OpExecutionContext,
    person_removal: PersonRemovalContext,
) -> None:
    """Mark a person_removal request as COMPLETED."""
    from django.utils import timezone

    # Accept FAILED too so a Dagster re-run after a mid-job failure (where the failure hook already
    # flipped the request to FAILED) can still finalize it. See finalize_deletion_request.
    DataDeletionRequest.objects.filter(
        pk=person_removal.request_id,
        status__in=[RequestStatus.IN_PROGRESS, RequestStatus.FAILED],
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
        or ops_config.get("load_hogql_event_removal_request", {}).get("config", {}).get("request_id")
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


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@dagster.job(tags=OWNER_TAG, hooks={mark_deletion_failed})
def data_deletion_request_event_removal():
    """Execute an approved event deletion request.

    Immediate mode: load → dynamic fan-out (one delete op per table and shard, parallel under the
    run executor) → verify (fan-in) → finalize. A failed shard is re-executed on its own with the
    Dagster UI's "Re-execute from failure"; finalize accepts the FAILED status the failure hook set,
    so the re-executed run completes the request.
    Deferred mode fans out nothing and queues event UUIDs into adhoc_events_deletion for the
    scheduled deletes_job to drain later.
    """
    request = load_deletion_request()
    shards = get_event_removal_shards(request)
    deleted = shards.map(lambda shard: delete_event_removal_shard(shard, request))
    result = complete_event_deletion(request, deleted.collect())
    finalize_deletion_request(result)


@dagster.job(tags=OWNER_TAG, hooks={mark_deletion_failed})
def data_deletion_request_hogql_event_removal():
    """Queue event UUIDs selected by an approved, team-scoped HogQL query."""
    request = load_hogql_event_removal_request()
    result = execute_hogql_event_deletion(request)
    finalize_hogql_event_removal(result)


@dagster.job(tags=OWNER_TAG, hooks={mark_deletion_failed})
def data_deletion_request_property_removal():
    """Execute an approved property removal request with one chain of ops per table and shard.

    load → dynamic fan-out (one target per events table and shard) → per target: copy cleaned rows
    to S3 → delete the originals → reingest the cleaned rows → verify, each its own op → verify
    (fan-in over all targets) → empty the staged copies → finalize.

    A failed step is re-executed individually via the Dagster UI's "Re-execute from failure".
    Progress files in S3 make every step skip work that already finished, so a fresh run from the
    admin Retry button is safe too. finalize accepts the FAILED status the failure hook set, so the
    re-executed run completes the request.
    """
    request = load_property_removal_request()
    targets = get_property_removal_shards(deletion_request=request)
    shard_stats = targets.map(
        lambda target: verify_property_removal_shard(
            reingest_property_removal_shard(
                delete_property_removal_shard(copy_property_removal_shard(target, request), request),
                request,
            ),
            request,
        )
    ).collect()
    verified = verify_property_removal(deletion_request=request, shard_stats=shard_stats)
    cleaned = cleanup_property_removal_staging(deletion_request=verified, shard_stats=shard_stats)
    finalize_deletion_request(cleaned)


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

DELETION_JOB_NAMES = [
    data_deletion_request_event_removal.name,
    data_deletion_request_hogql_event_removal.name,
    data_deletion_request_property_removal.name,
    data_deletion_request_person_removal.name,
]


@dagster.sensor(
    jobs=[
        data_deletion_request_event_removal,
        data_deletion_request_hogql_event_removal,
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
    for job_name in DELETION_JOB_NAMES:
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
    elif next_request.request_type == RequestType.HOGQL_EVENT_REMOVAL:
        job, load_op = data_deletion_request_hogql_event_removal, "load_hogql_event_removal_request"
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
        # Include attempt_count so retries / re-approvals of the same request get a
        # distinct run_key. Dagster dedupes by run_key, so a bare pk would make every
        # relaunch after the first a silent no-op. attempt_count is bumped exactly once
        # per APPROVED → IN_PROGRESS transition (see _mark_in_progress).
        run_key=f"{next_request.pk}:{next_request.attempt_count}",
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
# Verify-queued sweep job: promotes recently-QUEUED requests once events are gone
# ---------------------------------------------------------------------------


class VerifyQueuedConfig(dagster.Config):
    lookback_days: int = pydantic.Field(
        default=28,
        description="Only verify QUEUED requests created within this many days. Bounds the sweep so a "
        "permanently stuck request isn't re-checked forever.",
    )


@dagster.op(tags=OWNER_TAG)
def verify_queued_deletion_requests_op(context: dagster.OpExecutionContext, config: VerifyQueuedConfig) -> None:
    """Verify recently-QUEUED deletion requests and promote those whose events are gone."""
    from django.utils import timezone

    cutoff = timezone.now() - timedelta(days=config.lookback_days)
    queued = DataDeletionRequest.objects.filter(status=RequestStatus.QUEUED, created_at__gte=cutoff)
    promoted = 0
    still_queued = 0
    for request in queued:
        try:
            outcome = verify_queued_request(request)
        except Exception as exc:
            context.log.warning(f"Could not verify deletion request {request.pk}: {exc}")
            still_queued += 1
            continue
        if outcome.promoted:
            promoted += 1
            context.log.info(f"Deletion request {request.pk} promoted QUEUED → COMPLETED.")
        else:
            still_queued += 1
            context.log.info(f"Deletion request {request.pk}: {outcome.remaining} matching events remain, kept QUEUED.")
    context.add_output_metadata(
        {
            "promoted": dagster.MetadataValue.int(promoted),
            "still_queued": dagster.MetadataValue.int(still_queued),
            "lookback_days": dagster.MetadataValue.int(config.lookback_days),
        }
    )
    context.log.info(f"verify_queued_deletion_requests: {promoted} promoted, {still_queued} kept queued.")


@dagster.job(tags=OWNER_TAG)
def verify_queued_deletion_requests_job():
    verify_queued_deletion_requests_op()


# ---------------------------------------------------------------------------
# Auto-approve sweep job: approves pending event removals small enough to skip review
# ---------------------------------------------------------------------------


class AutoApproveConfig(dagster.Config):
    max_requests: int = pydantic.Field(
        default=50,
        ge=1,
        description="Most requests to evaluate in one tick. Each one costs a pair of ClickHouse "
        "queries, so this bounds what a backlog can spend before the next tick.",
    )


@dagster.op(tags=OWNER_TAG)
def auto_approve_pending_deletion_requests_op(context: dagster.OpExecutionContext, config: AutoApproveConfig) -> None:
    """Refresh stats on pending auto-approve candidates and approve the ones under the size limit."""
    outcome = auto_approve_pending_requests(max_requests=config.max_requests, on_event=context.log.info)
    context.add_output_metadata(
        {
            "approved": dagster.MetadataValue.int(outcome.approved),
            "skipped": dagster.MetadataValue.int(outcome.skipped),
            "errored": dagster.MetadataValue.int(outcome.errored),
            # Surfaced so a tick that hit the cap reads as truncated rather than as "that was all of them".
            "max_requests": dagster.MetadataValue.int(config.max_requests),
        }
    )
    context.log.info(
        f"auto_approve_pending_deletion_requests: {outcome.approved} approved, "
        f"{outcome.skipped} left pending, {outcome.errored} errored."
    )


@dagster.job(tags=OWNER_TAG)
def auto_approve_deletion_requests_job():
    """Approve pending event removals that are small enough to skip ClickHouse Team review.

    Stats are refreshed inside the job, immediately before the size decision, so the count it
    approves against is one it measured rather than one a person fetched at an unknown earlier time.
    """
    auto_approve_pending_deletion_requests_op()


@dagster.schedule(
    job=auto_approve_deletion_requests_job,
    cron_schedule=f"*/{AUTO_APPROVE_INTERVAL_MINUTES} * * * *",
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.STOPPED,
)
def auto_approve_deletion_requests_schedule():
    """Sweep for auto-approvable pending requests.

    Stopped by default like the rest of this feature's schedules and sensors — an operator turns it on
    in the Dagster UI, and nothing is auto-approved until they do.
    """
    return dagster.RunRequest()


# ---------------------------------------------------------------------------
# Verifier sensor: launches the sweep job after each deletes_job SUCCESS
# ---------------------------------------------------------------------------


@dagster.run_status_sensor(
    run_status=dagster.DagsterRunStatus.SUCCESS,
    monitored_jobs=[deletes_job],
    request_job=verify_queued_deletion_requests_job,
    default_status=dagster.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=60,
)
def verify_queued_deletion_requests(context: dagster.RunStatusSensorContext):
    """Launch the verify-queued sweep after each deletes_job SUCCESS (the weekend drain).

    deletes_job runs after the Saturday-night squash, so this fires once the adhoc-event
    deletion drain has completed. The sweep logic lives in verify_queued_deletion_requests_job.
    """
    return dagster.RunRequest(run_key=context.dagster_run.run_id)
