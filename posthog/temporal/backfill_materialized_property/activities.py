"""Activities for materialized property backfill workflow."""

import dataclasses
from typing import Optional

from django.db import transaction

import structlog
from temporalio import activity

from posthog.clickhouse.cluster import AlterTableMutationRunner, get_cluster
from posthog.models import MaterializedColumnSlot
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.event.sql import DMAT_STRING_COLUMN_COUNT
from posthog.models.materialized_column_slots import COMPACTION_FREE_COLUMN_THRESHOLD, MaterializedColumnSlotState
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync

from products.event_definitions.backend.models.property_definition import PropertyType

logger = structlog.get_logger(__name__)

# String-only column pool for the new batched workflow (per RFC).
# Other types remain in the legacy per-slot path for backwards compatibility with existing slots.
DMAT_STRING_COLUMN_NAME_PREFIX = "dmat_string_"

PROPERTY_TYPE_TO_COLUMN_NAME: dict[str, str] = {
    str(PropertyType.String): "string",
    str(PropertyType.Numeric): "numeric",
    str(PropertyType.Boolean): "bool",
    str(PropertyType.Datetime): "datetime",
}

# New slots created via the PENDING flow are always String. The other types remain
# in the codebase but are no longer accepted at the API layer — kept for query-time
# resolution of legacy slots that are still READY.
MATERIALIZABLE_PROPERTY_TYPES: set[str] = {str(PropertyType.String)}


@dataclasses.dataclass
class BackfillMaterializedColumnInputs:
    team_id: int
    property_name: str
    property_type: str
    mat_column_name: str
    partition_id: Optional[str] = None


@dataclasses.dataclass
class UpdateSlotStateInputs:
    slot_id: str
    state: str
    error_message: Optional[str] = None


def _generate_property_extraction_sql(property_type: str) -> str:
    """
    Generate SQL expression to extract property value from JSON properties column.

    Uses %(property_name)s placeholder for safe parameterization (matching HogQL pattern).
    Caller must pass property_name in the query params dict.

    Mimics the HogQL property type wrappers (toFloat, toBool, toDateTime) applied
    to JSON-extracted values to ensure identical behavior.
    """
    # Base JSON extraction with quote trimming and nullIf handling (same as HogQL printer)
    # HogQL pattern: replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(...), ''), 'null'), '^"|"$', '')
    base_extract = (
        "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, %(property_name)s), ''), 'null'), '^\"|\"$', '')"
    )

    if property_type == PropertyType.String:
        return base_extract

    elif property_type == PropertyType.Numeric:
        # Match HogQL's toFloat() - no whitespace trimming, just direct conversion
        return f"toFloat64OrNull({base_extract})"

    elif property_type == PropertyType.Boolean:
        # Match HogQL's toBool(transform(toString(...), ["true", "false"], [1, 0], None))
        # Need to use toString() wrapper to match HogQL behavior
        return f"transform(toString({base_extract}), ['true', 'false'], [1, 0], NULL)"

    elif property_type == PropertyType.Datetime:
        # Match HogQL's toDateTime() -> parseDateTime64BestEffortOrNull with precision 6
        # See posthog/hogql/printer.py L1391-1392 and posthog/hogql/functions/clickhouse/conversions.py L112-127
        # Timezone param omitted - uses server default (UTC). Most datetime strings have explicit
        # timezone info anyway, and for ambiguous strings UTC is a reasonable default.
        return f"parseDateTime64BestEffortOrNull({base_extract}, 6)"

    else:
        raise ValueError(f"Unsupported property type for materialization: {property_type}")


@activity.defn
def backfill_materialized_column(inputs: BackfillMaterializedColumnInputs) -> int:
    """
    Backfill a materialized column by running ALTER TABLE UPDATE on historical events.

    Runs the mutation on all shards since sharded_events is a sharded table.
    Uses mutations_sync=1 to block until each shard's mutation completes.

    Returns 0 (row count not tracked).
    """
    extraction_sql = _generate_property_extraction_sql(inputs.property_type)

    partition_clause = "IN PARTITION %(partition_id)s" if inputs.partition_id else ""
    query = f"""
        ALTER TABLE sharded_events
        UPDATE {inputs.mat_column_name} = {extraction_sql}
        {partition_clause}
        WHERE team_id = %(team_id)s
    """

    params: dict[str, str | int] = {
        "team_id": inputs.team_id,
        "property_name": inputs.property_name,
    }
    if inputs.partition_id:
        params["partition_id"] = inputs.partition_id

    logger.info(
        "Starting backfill for materialized column",
        team_id=inputs.team_id,
        property_name=inputs.property_name,
        property_type=inputs.property_type,
        mat_column_name=inputs.mat_column_name,
        partition_id=inputs.partition_id,
    )

    try:
        cluster = get_cluster()

        # Execute mutation on one host per shard with mutations_sync=1
        # This blocks until the mutation completes on each shard
        def run_mutation(client):
            client.execute(query, params, settings={"mutations_sync": 1})

        cluster.map_one_host_per_shard(run_mutation).result()

        logger.info(
            "Backfill mutation completed on all shards",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            mat_column_name=inputs.mat_column_name,
        )

        return 0

    except Exception as e:
        logger.exception(
            "Backfill failed",
            team_id=inputs.team_id,
            property_name=inputs.property_name,
            mat_column_name=inputs.mat_column_name,
            error=str(e),
        )
        raise


@activity.defn
def update_slot_state(inputs: UpdateSlotStateInputs) -> bool:
    """
    Update the state of a materialized column slot with activity logging.

    Returns True if update succeeded.
    """
    try:
        slot = MaterializedColumnSlot.objects.select_related("team", "property_definition").get(id=inputs.slot_id)
        old_state = slot.state

        slot.state = inputs.state

        # Store or clear error message
        if inputs.error_message:
            slot.error_message = inputs.error_message
            logger.error(
                "Slot state update with error",
                slot_id=inputs.slot_id,
                old_state=old_state,
                new_state=inputs.state,
                error_message=inputs.error_message,
            )
        elif inputs.state == "BACKFILL":
            # Clear error message when transitioning to BACKFILL (e.g., on retry)
            slot.error_message = None

        slot.save()

        logger.info(
            "Updated slot state",
            slot_id=inputs.slot_id,
            team_id=slot.team_id,
            old_state=old_state,
            new_state=inputs.state,
        )

        # Log activity for state transitions to READY or ERROR
        if inputs.state in ["READY", "ERROR"]:
            property_name = slot.property_definition.name if slot.property_definition else "Unknown"

            activity_name = (
                "materialized_column_backfill_completed"
                if inputs.state == "READY"
                else "materialized_column_backfill_failed"
            )

            log_activity(
                organization_id=slot.team.organization_id,
                team_id=slot.team_id,
                user=None,  # System user for workflow-triggered updates
                was_impersonated=False,
                item_id=str(slot.id),
                scope="DataManagement",
                activity=activity_name,
                detail=Detail(
                    name=property_name,
                    changes=[
                        Change(
                            type="MaterializedColumnSlot",
                            action="changed",
                            field="state",
                            before=old_state,
                            after=inputs.state,
                        ),
                    ],
                ),
            )

        return True

    except MaterializedColumnSlot.DoesNotExist:
        logger.warning("Slot not found for state update", slot_id=inputs.slot_id)
        return False
    except Exception as e:
        logger.exception("Failed to update slot state", slot_id=inputs.slot_id, error=str(e))
        raise


# ---------------------------------------------------------------------------
# Batched weekly workflow (new design — see RFC: dynamic property materialization)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _ColumnAssignment:
    """Plan for a single dmat_string column: which (team_id, property_name) pairs land in it."""

    column_index: int
    # List of (team_id, property_name, slot_id) — slot_id is the MaterializedColumnSlot UUID as a string.
    branches: list[tuple[int, str, str]]


@dataclasses.dataclass
class AssignPendingSlotsInputs:
    workflow_id: str


@dataclasses.dataclass
class AssignPendingSlotsResult:
    # column_index → list of (team_id, property_name, slot_id_str) tuples
    # Combines BOTH PENDING-slot assignments (writes to a fresh column) AND compaction targets
    # (writes to a smaller dense column for slots being repacked).
    assignments: list[_ColumnAssignment]
    # All slot IDs that were transitioned PENDING → BACKFILL by this activity.
    assigned_slot_ids: list[str]
    # Slot IDs whose compaction_target_slot_index was set (existing READY slots being repacked).
    # These remain in READY state during the mutation — HogQL keeps reading from the old column
    # while plugin-server dual-writes to both old and new columns. After the mutation completes,
    # finalize_compaction swaps them.
    compacted_slot_ids: list[str]


def _plan_column_assignments(
    pending_slots: list[MaterializedColumnSlot],
    used_indexes_by_team: dict[int, set[int]],
) -> list[_ColumnAssignment]:
    """
    Bin-pack PENDING slots into the smallest possible set of new column indexes.

    Each column may hold one (team_id, property) pair per team — different teams can
    share a column since each row belongs to one team. This minimises the number of
    columns consumed per cycle, which extends runway before compaction is needed.

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
                "Compaction is needed."
            )
        plan_by_column.setdefault(chosen, _ColumnAssignment(column_index=chosen, branches=[]))
        plan_by_column[chosen].branches.append((slot.team_id, slot.property_definition.name, str(slot.id)))
        team_columns_in_plan.setdefault(slot.team_id, set()).add(chosen)

    # Return assignments sorted by column index for stable SQL.
    return [plan_by_column[idx] for idx in sorted(plan_by_column)]


def _plan_compaction_targets(
    slots_to_compact: list[MaterializedColumnSlot],
    reserved_indexes: set[int],
) -> dict[str, int]:
    """
    Pack `slots_to_compact` into the smallest possible dense range of fresh column indexes
    that does not overlap `reserved_indexes` (which already includes the slots' current
    `slot_index` values, the assignments planned for new PENDING slots, and any other
    in-use columns across all teams).

    Returns slot_id → new compaction_target_slot_index. Each team in the plan gets at most
    one target per column; we walk slots in deterministic (team_id, id) order and pick the
    smallest column not yet assigned to that team.

    Slots that can't fit are silently skipped — they stay on their existing column for
    this cycle. Compaction is best-effort; the next weekly run will re-evaluate after some
    columns are freed.
    """
    sorted_slots = sorted(slots_to_compact, key=lambda s: (s.team_id, str(s.id)))
    team_targets: dict[int, set[int]] = {}
    plan: dict[str, int] = {}

    for slot in sorted_slots:
        team_used = team_targets.get(slot.team_id, set())
        chosen: int | None = None
        for col_idx in range(DMAT_STRING_COLUMN_COUNT):
            if col_idx in reserved_indexes:
                continue
            if col_idx in team_used:
                continue
            chosen = col_idx
            break
        if chosen is None:
            logger.warning(
                "Skipping slot in compaction — no fresh column fits without violating per-team uniqueness",
                slot_id=str(slot.id),
                team_id=slot.team_id,
                reserved_count=len(reserved_indexes),
                team_used_count=len(team_used),
            )
            continue
        plan[str(slot.id)] = chosen
        team_targets.setdefault(slot.team_id, set()).add(chosen)
        # Don't add `chosen` to reserved_indexes — other teams can share this column index
        # (per-team uniqueness is the only invariant). Only the per-team set above prevents
        # the same team from packing two slots into the same column on this run.

    return plan


@activity.defn
def assign_pending_slots(inputs: AssignPendingSlotsInputs) -> AssignPendingSlotsResult:
    """
    Atomically:
      1. Read all PENDING slots PLUS any BACKFILL slots already claimed by THIS workflow run
         (their backfill_temporal_workflow_id == inputs.workflow_id). The latter happens when
         the activity is retried after the DB transaction commits but before Temporal records
         the activity completion — without this, those slots would be silently stranded in
         BACKFILL forever and the next weekly run would never pick them up.
      2. If free-column count is below COMPACTION_FREE_COLUMN_THRESHOLD, mark every existing
         READY slot for compaction by populating `compaction_target_slot_index` with a fresh
         dense column index. Plugin-server reads pick this up on next cache refresh and start
         dual-writing to both columns.
      3. Compute column assignments for PENDING slots, avoiding per-team collisions with the
         union of existing slot_index, compaction_target_slot_index, and the in-progress plan.
      4. Update each PENDING slot in-place: set slot_index, transition to BACKFILL, stamp
         workflow_run_id (in `backfill_temporal_workflow_id`).

    Returns the combined assignment plan (PENDING new columns + compaction target columns)
    so the workflow can submit a single batched mutation that backfills both. Reclaimed slots
    are included in `assigned_slot_ids` and re-use their existing `slot_index` (we do NOT
    re-pack them — that would risk repeating a successful mutation against the wrong column).

    Stranded BACKFILL slots from PRIOR runs (workflow_id != current) are NOT reclaimed by this
    activity — they need operator intervention because we can't safely tell whether their
    mutation completed. We log a warning and a metric so they're observable.
    """
    logger.info("Assigning pending slots to columns", workflow_run_id=inputs.workflow_id)

    with transaction.atomic():
        # Lock both PENDING and READY rows we may modify.
        all_string_slots = list(
            MaterializedColumnSlot.objects.select_for_update()
            .select_related("property_definition", "team")
            .filter(property_type=str(PropertyType.String))
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
            and s.backfill_temporal_workflow_id == inputs.workflow_id
            and s.slot_index is not None
        ]
        if reclaimed_from_this_run:
            logger.info(
                "Reclaiming BACKFILL slots from a previous attempt of this workflow run",
                workflow_run_id=inputs.workflow_id,
                count=len(reclaimed_from_this_run),
                slot_ids=[str(s.id) for s in reclaimed_from_this_run],
            )

        # Stranded slots from OTHER runs — we don't auto-recover, but we make them visible.
        # An operator can manually transition them back to PENDING via the API's retry endpoint.
        stranded = [
            s
            for s in all_string_slots
            if s.state == MaterializedColumnSlotState.BACKFILL
            and s.backfill_temporal_workflow_id is not None
            and s.backfill_temporal_workflow_id != inputs.workflow_id
        ]
        if stranded:
            logger.warning(
                "Stranded BACKFILL slots from a prior workflow run — operator action required to retry",
                current_workflow_run_id=inputs.workflow_id,
                count=len(stranded),
                slot_ids=[str(s.id) for s in stranded],
                stale_workflow_ids=sorted({s.backfill_temporal_workflow_id for s in stranded}),
            )

        # Compaction trigger: count free string columns across the global pool. We trigger when
        # remaining capacity could fail to absorb a worst-case weekly cycle.
        used_indexes = {s.slot_index for s in all_string_slots if s.slot_index is not None} | {
            s.compaction_target_slot_index for s in all_string_slots if s.compaction_target_slot_index is not None
        }
        free_count = DMAT_STRING_COLUMN_COUNT - len(used_indexes)

        compaction_plan: dict[str, int] = {}
        slots_to_compact: list[MaterializedColumnSlot] = []
        if free_count < COMPACTION_FREE_COLUMN_THRESHOLD:
            # Compact every READY slot that does not already have a compaction target in flight.
            slots_to_compact = [
                s
                for s in all_string_slots
                if s.state == MaterializedColumnSlotState.READY
                and s.slot_index is not None
                and s.compaction_target_slot_index is None
            ]
            if slots_to_compact:
                logger.info(
                    "Triggering dmat compaction",
                    workflow_id=inputs.workflow_id,
                    free_count=free_count,
                    slots_to_compact=len(slots_to_compact),
                )
                # The compaction planner needs to avoid every column currently in use, plus
                # whatever PENDING assignments we're about to make below.
                compaction_plan = _plan_compaction_targets(slots_to_compact, set(used_indexes))

        if not pending and not compaction_plan and not reclaimed_from_this_run:
            logger.info(
                "Nothing to do — no PENDING slots, nothing reclaimed, and no compaction needed",
                workflow_run_id=inputs.workflow_id,
            )
            return AssignPendingSlotsResult(assignments=[], assigned_slot_ids=[], compacted_slot_ids=[])

        # PENDING-slot assignment: avoid every column currently in use across all teams,
        # PLUS the compaction targets we just allocated, PLUS each team's own existing slots.
        used_indexes_after_compaction = set(used_indexes) | set(compaction_plan.values())
        used_indexes_by_team: dict[int, set[int]] = {}
        for slot in all_string_slots:
            if slot.slot_index is not None:
                used_indexes_by_team.setdefault(slot.team_id, set()).add(slot.slot_index)
            if slot.compaction_target_slot_index is not None:
                used_indexes_by_team.setdefault(slot.team_id, set()).add(slot.compaction_target_slot_index)
        for slot in slots_to_compact:
            target = compaction_plan.get(str(slot.id))
            if target is not None:
                used_indexes_by_team.setdefault(slot.team_id, set()).add(target)

        # Fold the global "in use" set into per-team to keep the planner local.
        for team_id in {s.team_id for s in pending}:
            used_indexes_by_team.setdefault(team_id, set()).update(used_indexes_after_compaction)

        pending_assignments = _plan_column_assignments(pending, used_indexes_by_team) if pending else []

        # Apply PENDING assignments.
        slot_index_by_id: dict[str, int] = {}
        for assignment in pending_assignments:
            for _team_id, _prop_name, slot_id in assignment.branches:
                slot_index_by_id[slot_id] = assignment.column_index

        assigned_slot_ids: list[str] = []
        for slot in pending:
            slot.slot_index = slot_index_by_id[str(slot.id)]
            slot.state = MaterializedColumnSlotState.BACKFILL
            slot.backfill_temporal_workflow_id = inputs.workflow_id
            slot.error_message = None
            slot.save(
                update_fields=[
                    "slot_index",
                    "state",
                    "backfill_temporal_workflow_id",
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
                (slot.team_id, slot.property_definition.name, str(slot.id))
            )
            assigned_slot_ids.append(str(slot.id))

        # Apply compaction targets — these stay in READY state with compaction_target_slot_index set.
        # Slots that the planner skipped (couldn't fit) are simply left alone for this cycle and
        # picked up by the next weekly run after some columns get freed up.
        compacted_slot_ids: list[str] = []
        compaction_assignments_by_column: dict[int, _ColumnAssignment] = {}
        for slot in slots_to_compact:
            target = compaction_plan.get(str(slot.id))
            if target is None:
                continue
            slot.compaction_target_slot_index = target
            slot.save(update_fields=["compaction_target_slot_index"])
            compacted_slot_ids.append(str(slot.id))
            compaction_assignments_by_column.setdefault(target, _ColumnAssignment(column_index=target, branches=[]))
            compaction_assignments_by_column[target].branches.append(
                (slot.team_id, slot.property_definition.name, str(slot.id))
            )

        all_assignments = (
            pending_assignments
            + [reclaimed_assignments_by_column[idx] for idx in sorted(reclaimed_assignments_by_column)]
            + [compaction_assignments_by_column[idx] for idx in sorted(compaction_assignments_by_column)]
        )

    logger.info(
        "Assigned PENDING slots and compaction targets",
        workflow_run_id=inputs.workflow_id,
        assigned_count=len(assigned_slot_ids),
        reclaimed_count=len(reclaimed_from_this_run),
        compacted_count=len(compacted_slot_ids),
        column_count=len(all_assignments),
    )

    return AssignPendingSlotsResult(
        assignments=all_assignments,
        assigned_slot_ids=assigned_slot_ids,
        compacted_slot_ids=compacted_slot_ids,
    )


@dataclasses.dataclass
class RunBatchedMutationInputs:
    assignments: list[_ColumnAssignment]


# Soft cap on multiIf branches per ALTER TABLE statement. Each branch is roughly 250 chars
# (extract SQL + team_id literal + param ref). ClickHouse's default `max_query_size` is
# 256 KiB, so we cap chunks at ~500 branches to stay comfortably under the limit even with
# long property names. When a cycle exceeds this, the activity submits multiple sequential
# mutations rather than one giant one.
MAX_MULTIIF_BRANCHES_PER_MUTATION = 500


def _chunk_assignments_by_branch_count(
    assignments: list[_ColumnAssignment], max_branches: int
) -> list[list[_ColumnAssignment]]:
    """Split assignments so each chunk has at most `max_branches` branches in total.

    Splits at column boundaries — never breaks a single column's multiIf across mutations,
    because the multiIf is self-contained per column. A column with more branches than
    `max_branches` lands in its own chunk on its own (and may individually exceed the cap;
    the caller logs a warning in that case).
    """
    chunks: list[list[_ColumnAssignment]] = []
    current: list[_ColumnAssignment] = []
    current_count = 0

    for assignment in assignments:
        branch_count = len(assignment.branches)
        if current and current_count + branch_count > max_branches:
            chunks.append(current)
            current = []
            current_count = 0
        current.append(assignment)
        current_count += branch_count

    if current:
        chunks.append(current)

    return chunks


def _build_batched_update_command(assignments: list[_ColumnAssignment]) -> tuple[str, dict[str, str]]:
    """
    Build the body of a single ALTER TABLE UPDATE that populates one or more dmat_string
    columns using a multiIf branch per (team, column) pair.

    Property names are passed as parameters to prevent SQL injection. team_ids are inlined
    as integer literals (safe — they originate from a typed PositiveSmallIntegerField).

    Returns (command, params) suitable for AlterTableMutationRunner.
    """
    if not assignments:
        raise ValueError("Cannot build mutation command with no assignments")

    set_clauses: list[str] = []
    params: dict[str, str] = {}
    all_team_ids: set[int] = set()

    for assignment in assignments:
        col_name = f"{DMAT_STRING_COLUMN_NAME_PREFIX}{assignment.column_index}"
        branches: list[str] = []
        for team_id, property_name, slot_id in assignment.branches:
            # slot_id is unique → param key is collision-free across the entire mutation.
            param_key = f"prop_{slot_id.replace('-', '')}"
            params[param_key] = property_name
            extract_sql = (
                "replaceRegexpAll("
                f"nullIf(nullIf(JSONExtractRaw(properties, %({param_key})s), ''), 'null'),"
                " '^\"|\"$', ''"
                ")"
            )
            branches.append(f"team_id = {int(team_id)}")
            branches.append(extract_sql)
            all_team_ids.add(team_id)
        # Trailing default keeps any pre-existing value (zero-cost no-op for unaffected rows).
        branches.append(col_name)
        set_clauses.append(f"{col_name} = multiIf({', '.join(branches)})")

    team_ids_sorted = sorted(all_team_ids)
    where_clause = f"team_id IN ({', '.join(str(tid) for tid in team_ids_sorted)})"
    command = f"UPDATE {', '.join(set_clauses)} WHERE {where_clause}"
    return command, params


@activity.defn
def run_batched_mutation(inputs: RunBatchedMutationInputs) -> None:
    """
    Submit (or attach to an existing) batched ALTER TABLE UPDATE mutation and block until
    it completes on every shard.

    Uses AlterTableMutationRunner which:
      - is idempotent — re-running with the same command attaches to the existing mutation
      - submits with the cluster's default settings (mutations_sync=0 outside tests),
        then polls system.mutations on each replica until is_done=1

    When the assignments would produce a SQL string larger than ClickHouse's
    `max_query_size` (256 KiB by default), the activity splits them into multiple
    sequential mutations. This caps the per-mutation read cost at the price of running
    several mutations back-to-back instead of one big one — both are equivalent in terms
    of total work since each mutation reads `properties` once per matching row.
    """
    if not inputs.assignments:
        logger.info("No assignments to backfill — skipping mutation")
        return

    chunks = _chunk_assignments_by_branch_count(inputs.assignments, MAX_MULTIIF_BRANCHES_PER_MUTATION)

    total_branches = sum(len(a.branches) for a in inputs.assignments)
    logger.info(
        "Submitting batched dmat backfill mutation",
        column_count=len(inputs.assignments),
        team_count=len({tid for a in inputs.assignments for tid, _, _ in a.branches}),
        branch_count=total_branches,
        chunk_count=len(chunks),
    )

    # Sync activity that may run for hours — without periodic heartbeats Temporal
    # will kill it as soon as `heartbeat_timeout` elapses. The HeartbeaterSync
    # context manager spawns a background thread that calls `activity.heartbeat()`
    # at heartbeat_timeout / 12.
    with HeartbeaterSync(logger=logger):
        cluster = get_cluster()
        for chunk_index, chunk in enumerate(chunks):
            chunk_branches = sum(len(a.branches) for a in chunk)
            if chunk_branches > MAX_MULTIIF_BRANCHES_PER_MUTATION:
                # Single column with too many branches — let it through but warn so we notice.
                # If this fires repeatedly the per-team cap or the column-packing strategy
                # needs revisiting (e.g. raise MAX_SLOTS_PER_TEAM or pack fewer teams per column).
                logger.warning(
                    "Single-column chunk exceeds branch cap — submitting anyway, may hit max_query_size",
                    chunk_branches=chunk_branches,
                    column_index=chunk[0].column_index if chunk else None,
                )

            command, params = _build_batched_update_command(chunk)
            runner = AlterTableMutationRunner(
                table="sharded_events",
                commands={command},
                parameters=params,
            )
            runner.run_on_shards(cluster)
            logger.info(
                "Mutation chunk complete on all shards",
                chunk_index=chunk_index + 1,
                total_chunks=len(chunks),
                chunk_branches=chunk_branches,
            )

    logger.info("All batched dmat backfill mutation chunks complete", chunk_count=len(chunks))


@dataclasses.dataclass
class ActivateSlotsInputs:
    slot_ids: list[str]


@activity.defn
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
class FinalizeCompactionInputs:
    slot_ids: list[str]


@activity.defn
def finalize_compaction(inputs: FinalizeCompactionInputs) -> int:
    """
    After the batched mutation has populated `compaction_target_slot_index` columns,
    swap each compacted slot's `slot_index` ← `compaction_target_slot_index` and clear
    the target. The slot remains READY throughout — the only observable change is which
    dmat_string column HogQL reads from on the next query.

    The whole batch swaps in a single transaction with `select_for_update()` so a
    crash mid-loop rolls back cleanly (Postgres transactional guarantee), and so the
    activity is correct under retry: re-running it produces the same final state and
    we don't end up with a half-swapped batch confusing the planner on the next
    workflow run. Inside the transaction we also assert per-team uniqueness of the
    target column index against the *other* slots — if some operator hand-edited the
    table or a future planner bug let two slots claim the same target column for the
    same team, we fail loudly rather than silently violating the unique constraint.

    Until plugin-server caches refresh (~3 min), ingestion may still write to the OLD column
    for in-flight events. That data is harmless (no slot reads it) and the column is fully
    free for reuse on the next compaction cycle.
    """
    if not inputs.slot_ids:
        return 0

    swapped = 0
    with transaction.atomic():
        slots = list(
            MaterializedColumnSlot.objects.select_for_update()
            .select_related("team", "property_definition")
            .filter(
                id__in=inputs.slot_ids,
                compaction_target_slot_index__isnull=False,
            )
        )
        for slot in slots:
            old_slot_index = slot.slot_index
            new_slot_index = slot.compaction_target_slot_index
            collision = (
                MaterializedColumnSlot.objects.filter(
                    team_id=slot.team_id,
                    property_type=slot.property_type,
                    slot_index=new_slot_index,
                )
                .exclude(id=slot.id)
                .exists()
            )
            if collision:
                # The planner must never let two slots in the same team end up on the same
                # column. If we see this, something has corrupted the slot table — abort the
                # whole transaction so the operator can investigate before any swap is committed.
                raise RuntimeError(
                    f"Cannot finalize compaction for slot {slot.id}: "
                    f"team {slot.team_id} already has another {slot.property_type} slot at column "
                    f"{new_slot_index}. Aborting the entire compaction batch — investigate slot "
                    f"table state before retrying."
                )
            slot.slot_index = new_slot_index
            slot.compaction_target_slot_index = None
            slot.save(update_fields=["slot_index", "compaction_target_slot_index", "updated_at"])
            swapped += 1

            log_activity(
                organization_id=slot.team.organization_id,
                team_id=slot.team_id,
                user=None,
                was_impersonated=False,
                item_id=str(slot.id),
                scope="DataManagement",
                activity="materialized_column_compacted",
                detail=Detail(
                    name=slot.property_definition.name,
                    changes=[
                        Change(
                            type="MaterializedColumnSlot",
                            action="changed",
                            field="slot_index",
                            before=old_slot_index,
                            after=new_slot_index,
                        ),
                    ],
                ),
            )

    logger.info("Finalized compaction", swapped=swapped, requested=len(inputs.slot_ids))
    return swapped


@dataclasses.dataclass
class ClearCompactionTargetsInputs:
    slot_ids: list[str]


@activity.defn
def clear_compaction_targets(inputs: ClearCompactionTargetsInputs) -> int:
    """
    Reset `compaction_target_slot_index = NULL` on the given slots.

    Used when a batched mutation fails: the slots stay READY on their original column
    (no data loss), but the cancelled new column is freed for reuse on the next compaction
    cycle. Plugin-server caches will refresh and stop dual-writing within ~3 minutes.
    """
    if not inputs.slot_ids:
        return 0

    cleared = MaterializedColumnSlot.objects.filter(
        id__in=inputs.slot_ids,
        compaction_target_slot_index__isnull=False,
    ).update(compaction_target_slot_index=None)

    logger.info("Cleared compaction targets after mutation failure", cleared=cleared, requested=len(inputs.slot_ids))
    return cleared


@dataclasses.dataclass
class FailSlotsInputs:
    slot_ids: list[str]
    error_message: str


@activity.defn
def fail_slots(inputs: FailSlotsInputs) -> int:
    """
    Transition the given slot IDs to ERROR with the supplied error_message. Used when the
    batched mutation fails — operators can later transition them back to PENDING for retry.
    """
    if not inputs.slot_ids:
        return 0

    failed = 0
    for slot in MaterializedColumnSlot.objects.select_related("team", "property_definition").filter(
        id__in=inputs.slot_ids
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
