"""Activities for materialized property backfill workflow."""

import time
import hashlib
import dataclasses

from django.conf import settings
from django.db import transaction

import structlog
import posthoganalytics
from temporalio import activity

from posthog.clickhouse.cluster import AlterTableMutationRunner, get_cluster
from posthog.clickhouse.kafka_engine import json_extract_trim_quotes
from posthog.clickhouse.materialized_columns import DMAT_STRING_COLUMN_NAME_PREFIX
from posthog.models import MaterializedColumnSlot
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.dmat_slot_assignments.sql import (
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME,
    INSERT_DMAT_SLOT_ASSIGNMENTS_SQL,
    RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
    TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL,
)
from posthog.models.event.sql import DMAT_STRING_COLUMN_COUNT
from posthog.models.materialized_column_slots import MaterializedColumnSlotState
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)


def _generate_property_extraction_sql(property_name_param: str = "property_name") -> str:
    """SQL fragment that extracts one property out of `properties` as a string."""
    return json_extract_trim_quotes("properties", f"%({property_name_param})s")


@dataclasses.dataclass(order=True)
class _SlotBranch:
    """One team's property mapped to a dmat column."""

    team_id: int
    property_name: str
    slot_id: str


@dataclasses.dataclass
class _ColumnAssignment:
    """Plan for a single dmat_string column: which (team_id, property_name) pairs land in it."""

    column_index: int
    branches: list[_SlotBranch]


@dataclasses.dataclass
class AssignPendingColumnsInputs:
    run_id: str


@dataclasses.dataclass
class AssignPendingColumnsResult:
    assignments: list[_ColumnAssignment]
    assigned_slot_ids: list[str]


def _plan_column_assignments(
    pending_slots: list[MaterializedColumnSlot],
    used_indexes_by_team: dict[int, set[int]],
) -> list[_ColumnAssignment]:
    """
    Pack PENDING slots into the smallest available column index per team.

    Slot indices are shared across teams — `dmat_string_3` carries team A's "browser_name"
    and team B's "page_url" simultaneously, and the dmat dictionary resolves
    (team_id, column_index) → property_name per row. Per-team uniqueness on the column
    index is the only invariant.

    The greedy algorithm walks pending slots in deterministic order (team_id ASC, slot
    UUID ASC) and places each into the smallest column index that:
      - is not already used by that team in any other slot (PENDING/BACKFILL/READY), and
      - has not yet been assigned to that team during this run.
    """
    # Sort for deterministic packing — important for idempotent retries.
    pending_sorted = sorted(pending_slots, key=lambda s: (s.team_id, str(s.id)))

    plan_by_column: dict[int, _ColumnAssignment] = {}
    # Track which columns each team has already been placed into during this run.
    team_columns_in_plan: dict[int, set[int]] = {}

    for slot in pending_sorted:
        team_used = used_indexes_by_team.get(slot.team_id, set()) | team_columns_in_plan.get(slot.team_id, set())
        # Find the smallest column index not used by this team.
        chosen: int | None = None
        for col_idx in range(DMAT_STRING_COLUMN_COUNT):
            if col_idx not in team_used:
                chosen = col_idx
                break
        if chosen is None:
            raise RuntimeError(
                f"No free column index available for team {slot.team_id} (uses {sorted(team_used)}). "
                f"Team has saturated all {DMAT_STRING_COLUMN_COUNT} dmat columns."
            )
        plan_by_column.setdefault(chosen, _ColumnAssignment(column_index=chosen, branches=[]))
        plan_by_column[chosen].branches.append(
            _SlotBranch(team_id=slot.team_id, property_name=slot.property_definition.name, slot_id=str(slot.id))
        )
        team_columns_in_plan.setdefault(slot.team_id, set()).add(chosen)

    # Return assignments sorted by column index for stable SQL.
    return [plan_by_column[idx] for idx in sorted(plan_by_column)]


@activity.defn
@close_db_connections
def assign_pending_columns(inputs: AssignPendingColumnsInputs) -> AssignPendingColumnsResult:
    """Atomically allocate columns for PENDING slots and transition them to BACKFILL.

    Also reclaims any BACKFILL slots already stamped with THIS run_id — they're a retry of
    a previous attempt that committed the slot transition but didn't record activity
    completion. Reclaimed slots keep their existing `slot_index` (re-packing would risk
    re-running a finished mutation against a different column).

    Stranded BACKFILL slots from OTHER runs are logged + alerted but not auto-recovered —
    we can't tell if their mutation completed.
    """
    logger.info("Assigning pending slots to columns", run_id=inputs.run_id)

    with transaction.atomic():
        # Lock everything we'll inspect for collision avoidance — single shared pool, no
        # per-type filter (all dmat columns are `Nullable(String)`, HogQL casts at read).
        all_string_slots = list(
            MaterializedColumnSlot.objects.select_for_update()
            .select_related("property_definition", "team")
            .order_by("team_id", "id")
        )

        pending = [s for s in all_string_slots if s.state == MaterializedColumnSlotState.PENDING]

        # Detect slots already claimed by this workflow_run_id (activity retry case).
        # Their slot_index is already assigned and their column may have already been backfilled
        # by a prior run-batched-mutation invocation — we re-include them in the assignments so
        # the mutation runs idempotently (AlterTableMutationRunner is itself idempotent).
        reclaimed_from_this_run = [
            s
            for s in all_string_slots
            if s.state == MaterializedColumnSlotState.BACKFILL
            and s.backfill_temporal_run_id == inputs.run_id
            and s.slot_index is not None
        ]
        if reclaimed_from_this_run:
            logger.info(
                "Reclaiming BACKFILL slots from a previous attempt of this workflow run",
                run_id=inputs.run_id,
                count=len(reclaimed_from_this_run),
                slot_ids=[str(s.id) for s in reclaimed_from_this_run],
            )

        # Stranded slots from OTHER runs — we don't auto-recover, but we make them visible.
        # An operator can manually transition them back to PENDING via the API's retry endpoint.
        stranded = [
            s
            for s in all_string_slots
            if s.state == MaterializedColumnSlotState.BACKFILL
            and s.backfill_temporal_run_id is not None
            and s.backfill_temporal_run_id != inputs.run_id
        ]
        if stranded:
            stale_run_ids = sorted(
                {s.backfill_temporal_run_id for s in stranded if s.backfill_temporal_run_id is not None}
            )
            stranded_slot_ids = [str(s.id) for s in stranded]
            logger.warning(
                "Stranded BACKFILL slots from a prior workflow run — operator action required to retry",
                current_run_id=inputs.run_id,
                count=len(stranded),
                slot_ids=stranded_slot_ids,
                stale_run_ids=stale_run_ids,
            )
            # Surface to Sentry — the workflow doesn't fail (HogQL falls back to JSON for
            # state != READY) but stranded slots hold a column index until an operator resets
            # them to PENDING.
            posthoganalytics.capture_exception(
                Exception("dmat: stranded BACKFILL slots require operator action"),
                properties={
                    "current_run_id": inputs.run_id,
                    "stranded_slot_ids": stranded_slot_ids,
                    "stale_run_ids": stale_run_ids,
                },
            )

        if not pending and not reclaimed_from_this_run:
            logger.info(
                "Nothing to do — no PENDING slots and nothing reclaimed",
                run_id=inputs.run_id,
            )
            return AssignPendingColumnsResult(assignments=[], assigned_slot_ids=[])

        # PENDING-slot assignment: per-team free pool. Each team picks freely from
        # 0..DMAT_STRING_COLUMN_COUNT-1 — different teams can share the same column index for
        # different properties, the dmat dict resolves (team_id, slot_index) → property_name
        # per row.
        used_indexes_by_team: dict[int, set[int]] = {}
        for slot in all_string_slots:
            if slot.slot_index is not None:
                used_indexes_by_team.setdefault(slot.team_id, set()).add(slot.slot_index)

        pending_assignments = _plan_column_assignments(pending, used_indexes_by_team) if pending else []

        # Apply PENDING assignments.
        slot_index_by_id: dict[str, int] = {}
        for assignment in pending_assignments:
            for branch in assignment.branches:
                slot_index_by_id[branch.slot_id] = assignment.column_index

        assigned_slot_ids: list[str] = []
        for slot in pending:
            slot.slot_index = slot_index_by_id[str(slot.id)]
            slot.state = MaterializedColumnSlotState.BACKFILL
            slot.backfill_temporal_run_id = inputs.run_id
            slot.error_message = None
            slot.save(
                update_fields=[
                    "slot_index",
                    "state",
                    "backfill_temporal_run_id",
                    "error_message",
                    "updated_at",
                ]
            )
            assigned_slot_ids.append(str(slot.id))

        # Re-include reclaimed slots in the assignment plan so the mutation runs against
        # them too (idempotent — the mutation runner attaches to an existing mutation if one
        # for the same command is already in flight or done).
        reclaimed_assignments_by_column: dict[int, _ColumnAssignment] = {}
        for slot in reclaimed_from_this_run:
            assert slot.slot_index is not None  # filtered above
            reclaimed_assignments_by_column.setdefault(
                slot.slot_index, _ColumnAssignment(column_index=slot.slot_index, branches=[])
            )
            reclaimed_assignments_by_column[slot.slot_index].branches.append(
                _SlotBranch(team_id=slot.team_id, property_name=slot.property_definition.name, slot_id=str(slot.id))
            )
            assigned_slot_ids.append(str(slot.id))

        all_assignments = pending_assignments + [
            reclaimed_assignments_by_column[idx] for idx in sorted(reclaimed_assignments_by_column)
        ]

    logger.info(
        "Assigned PENDING slots",
        run_id=inputs.run_id,
        assigned_count=len(assigned_slot_ids),
        reclaimed_count=len(reclaimed_from_this_run),
        column_count=len(all_assignments),
    )

    return AssignPendingColumnsResult(
        assignments=all_assignments,
        assigned_slot_ids=assigned_slot_ids,
    )


@dataclasses.dataclass
class PopulateSlotAssignmentsInputs:
    pass


@dataclasses.dataclass
class PopulateSlotAssignmentsResult:
    rows_written: int


@activity.defn
@close_db_connections
def populate_slot_assignments(inputs: PopulateSlotAssignmentsInputs) -> PopulateSlotAssignmentsResult:
    """Sync slot assignments from Postgres to `dmat_slot_assignments` on every host, then
    reload `dmat_slot_assignments_dict` everywhere.

    Two-phase: TRUNCATE+INSERT on every host, then RELOAD on every host. If any host
    fails the populate, the reload never runs — the next mutation won't see a partially-
    populated cluster.
    """
    rows: list[tuple[int, int, str]] = []
    for slot in (
        MaterializedColumnSlot.objects.select_related("property_definition")
        .filter(state__in=[MaterializedColumnSlotState.READY, MaterializedColumnSlotState.BACKFILL])
        .order_by("team_id", "id")
    ):
        if slot.slot_index is not None:
            rows.append((slot.team_id, int(slot.slot_index), slot.property_definition.name))

    truncate_sql = TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL()
    insert_sql = INSERT_DMAT_SLOT_ASSIGNMENTS_SQL()
    reload_sql = RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL()

    def populate(client) -> int:
        client.execute(truncate_sql)
        if rows:
            client.execute(insert_sql, rows)
        return len(rows)

    def reload(client) -> None:
        client.execute(reload_sql)

    cluster = get_cluster()
    populate_results = cluster.map_all_hosts(populate).result()
    cluster.map_all_hosts(reload).result()

    rows_written = next(iter(populate_results.values()), 0)
    logger.info(
        "Populated dmat_slot_assignments and reloaded dictionary on all hosts",
        host_count=len(populate_results),
        rows_per_host=rows_written,
    )
    return PopulateSlotAssignmentsResult(rows_written=rows_written)


@dataclasses.dataclass
class RunBatchedMutationInputs:
    assignments: list[_ColumnAssignment]
    # See `compute_cycle_marker_int` — embedded in the mutation WHERE so SQL text differs
    # across cycles, defeating AlterTableMutationRunner's cross-cycle dedup.
    cycle_marker_int: int


def compute_cycle_marker_int(workflow_run_id: str) -> int:
    """Stable 32-bit unsigned int from `workflow_run_id` — same across activity retries
    within one cycle, different across cycles. Hash is non-cryptographic (just an
    identity bucket), so SHA-256 over a sliced 4-byte prefix is fine here."""
    return int.from_bytes(hashlib.sha256(workflow_run_id.encode()).digest()[:4], "big")


def _build_dict_backed_update_command(
    assignments: list[_ColumnAssignment], cycle_marker_int: int
) -> tuple[str, dict[str, str]]:
    """Build a single ALTER TABLE UPDATE that populates the given dmat_string columns by
    reading (team_id, column_index) → property_name out of `dmat_slot_assignments_dict`.

    Each column gets `col = if(dictHas(...), <extract>, col)`. The `<extract>` wraps
    `JSONExtractRaw` in the same shape as `_generate_property_extraction_sql` so the
    coercion contract pinned by `coercion_fixtures.json` is preserved.

    The WHERE uses `team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments)` so
    the SQL is constant-size regardless of team count, and ClickHouse can prune sharded_events
    parts that don't contain any of those teams.

    Returns `(command, {})` — property names live in the dict, not in query parameters.
    """
    if not assignments:
        raise ValueError("Cannot build mutation command with no assignments")

    # Fully-qualified identifiers — ClickHouse normalizes bare references when storing
    # `system.mutations.command`, and a bare-vs-qualified mismatch defeats the byte-equality
    # dedup join in `AlterTableMutationRunner.find_existing_mutations`.
    qualified_dict = f"{settings.CLICKHOUSE_DATABASE}.{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}"
    qualified_assignments_table = f"{settings.CLICKHOUSE_DATABASE}.dmat_slot_assignments"
    set_clauses: list[str] = []
    for assignment in assignments:
        idx = int(assignment.column_index)
        col_name = f"{DMAT_STRING_COLUMN_NAME_PREFIX}{idx}"
        property_name_expr = f"dictGetString('{qualified_dict}', 'property_name', (team_id, {idx}))"
        extract_sql = (
            f"replaceRegexpAll("
            f"nullIf(nullIf("
            f"JSONExtractRaw(properties, {property_name_expr})"
            f", ''), 'null')"
            f", '^\"|\"$', '')"
        )
        dispatch_sql = f"if(dictHas('{qualified_dict}', (team_id, {idx})), {extract_sql}, {col_name})"
        set_clauses.append(f"{col_name} = {dispatch_sql}")

    where_clause = (
        f"team_id IN (SELECT DISTINCT team_id FROM {qualified_assignments_table}) "
        f"AND {int(cycle_marker_int)} = {int(cycle_marker_int)}"
    )
    command = f"UPDATE {', '.join(set_clauses)} WHERE {where_clause}"
    return command, {}


@activity.defn
def run_batched_mutation(inputs: RunBatchedMutationInputs) -> None:
    """Submit (or attach to) the batched ALTER TABLE UPDATE and block until done on every
    shard. Reads property names from `dmat_slot_assignments_dict`, which
    `populate_slot_assignments` must have synced and reloaded first.
    """
    if not inputs.assignments:
        logger.info("No assignments to backfill — skipping mutation")
        return

    column_indexes = sorted({a.column_index for a in inputs.assignments})
    logger.info(
        "Submitting dict-backed dmat backfill mutation",
        column_count=len(inputs.assignments),
        column_indexes=column_indexes,
        cycle_marker_int=inputs.cycle_marker_int,
    )

    command, params = _build_dict_backed_update_command(inputs.assignments, inputs.cycle_marker_int)

    # The mutation can run for hours; HeartbeaterSync keeps Temporal from killing the
    # activity at `heartbeat_timeout`.
    t0 = time.monotonic()
    with HeartbeaterSync(logger=logger):
        cluster = get_cluster()
        runner = AlterTableMutationRunner(
            table="sharded_events",
            commands={command},
            parameters=params,
        )
        runner.run_on_shards(cluster)
    duration_seconds = time.monotonic() - t0

    logger.info(
        "Dict-backed dmat backfill mutation complete",
        column_count=len(inputs.assignments),
        duration_seconds=round(duration_seconds, 1),
    )
    posthoganalytics.capture(
        "dmat_mutation_completed",
        distinct_id="dmat-system",
        properties={
            "column_count": len(inputs.assignments),
            "column_indexes": column_indexes,
            "cycle_marker_int": inputs.cycle_marker_int,
            "duration_seconds": round(duration_seconds, 1),
        },
    )


@dataclasses.dataclass
class ActivateSlotsInputs:
    slot_ids: list[str]


@activity.defn
@close_db_connections
def activate_slots(inputs: ActivateSlotsInputs) -> int:
    """
    Transition the given slot IDs from BACKFILL → READY in a single bulk update.

    Logs an audit entry per slot to keep parity with the legacy per-slot workflow.
    """
    if not inputs.slot_ids:
        return 0

    activated = 0
    for slot in MaterializedColumnSlot.objects.select_related("team", "property_definition").filter(
        id__in=inputs.slot_ids,
        state=MaterializedColumnSlotState.BACKFILL,
    ):
        old_state = slot.state
        slot.state = MaterializedColumnSlotState.READY
        slot.error_message = None
        slot.save(update_fields=["state", "error_message"])
        activated += 1

        log_activity(
            organization_id=slot.team.organization_id,
            team_id=slot.team_id,
            user=None,
            was_impersonated=False,
            item_id=str(slot.id),
            scope="DataManagement",
            activity="materialized_column_backfill_completed",
            detail=Detail(
                name=slot.property_definition.name,
                changes=[
                    Change(
                        type="MaterializedColumnSlot",
                        action="changed",
                        field="state",
                        before=old_state,
                        after=str(MaterializedColumnSlotState.READY),
                    ),
                ],
            ),
        )

    logger.info("Activated slots", count=activated, requested=len(inputs.slot_ids))
    return activated


@dataclasses.dataclass
class FailSlotsInputs:
    slot_ids: list[str]
    error_message: str


@activity.defn
@close_db_connections
def fail_slots(inputs: FailSlotsInputs) -> int:
    """
    Transition the given slot IDs to ERROR with the supplied error_message. Used when the
    batched mutation fails — operators can later transition them back to PENDING for retry.
    """
    if not inputs.slot_ids:
        return 0

    failed = 0
    for slot in MaterializedColumnSlot.objects.select_related("team", "property_definition").filter(
        id__in=inputs.slot_ids,
        state=MaterializedColumnSlotState.BACKFILL,
    ):
        old_state = slot.state
        slot.state = MaterializedColumnSlotState.ERROR
        slot.error_message = inputs.error_message
        slot.save(update_fields=["state", "error_message"])
        failed += 1

        log_activity(
            organization_id=slot.team.organization_id,
            team_id=slot.team_id,
            user=None,
            was_impersonated=False,
            item_id=str(slot.id),
            scope="DataManagement",
            activity="materialized_column_backfill_failed",
            detail=Detail(
                name=slot.property_definition.name,
                changes=[
                    Change(
                        type="MaterializedColumnSlot",
                        action="changed",
                        field="state",
                        before=old_state,
                        after=str(MaterializedColumnSlotState.ERROR),
                    ),
                ],
            ),
        )

    return failed
