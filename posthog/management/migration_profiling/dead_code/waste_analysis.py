"""Waste analysis — how much of the migrate runtime would survive a re-squash?

The framing is simple: the **final database state** is what matters. The
fastest path to that state is one squashed initial migration per app. Every
operation that doesn't contribute to the final state — every column added
then dropped, every duplicate `AlterField`, every backfill against tables
that are now empty — is overhead on a fresh-DB migrate.

This module computes three things from the AST timeline + profile JSONL:

1. **The "alive set"** — which (app, model, field), (app, model), (app, model,
   index) tuples still exist after all migrations have applied.
2. **A per-op category** based on whether the op contributes to alive state
   or is purely transient.
3. **An aggregated breakdown** of SQL time, Migration.apply wall-clock, and
   estimated avoidable share.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from posthog.management.migration_profiling.dead_code.timeline import Timeline

# ---------- categories ----------


class WasteCategory:
    """Names match what gets rendered in the report. Keep stable."""

    ESSENTIAL_CREATE = "essential_create"  # CreateModel/AddField/AddIndex/AddConstraint for an alive target
    ESSENTIAL_RESHAPE = "essential_reshape"  # LAST AlterField on an alive field (the shape that survives)
    REDUNDANT_RESHAPE = "redundant_reshape"  # AlterField that's later re-altered or removed (overwritten)
    DEAD_TARGET = "dead_target"  # Op against a target that no longer exists
    REMOVAL = "removal"  # RemoveField/RemoveIndex/DeleteModel — by definition acts on a dead target
    BACKFILL = "backfill"  # RunPython — on fresh DB, no rows exist
    STATE_ONLY = "state_only"  # SDAS, AlterModelOptions etc — zero DB effect
    BOOTSTRAP = "bootstrap"  # Pre-migration DDL recorded in the synthetic frame
    UNKNOWN = "unknown"  # Anything not classifiable


AVOIDABLE_CATEGORIES: frozenset[str] = frozenset(
    {
        WasteCategory.REDUNDANT_RESHAPE,
        WasteCategory.DEAD_TARGET,
        WasteCategory.REMOVAL,
        WasteCategory.BACKFILL,
        WasteCategory.STATE_ONLY,
    }
)


# ---------- alive set ----------


@dataclass
class AliveSet:
    """What survives in the final schema after every migration applies."""

    fields: set[tuple[str, str, str]] = field(default_factory=set)  # (app, model, field)
    models: set[tuple[str, str]] = field(default_factory=set)  # (app, model)
    indexes: set[tuple[str, str, str]] = field(default_factory=set)  # (app, model, index_name)
    # Per-alive-target: the migration where its LAST AlterField lives (so we
    # can call only that one "essential reshape" and the rest "redundant").
    last_alter_per_field: dict[tuple[str, str, str], str] = field(default_factory=dict)


def compute_alive_set(timeline: Timeline) -> AliveSet:
    """Walk per-target event lists in order; if the last event is Add/Alter
    (not Remove), the target is alive.

    For RenameField we treat both old and new names as aliases of the same
    underlying field — the timeline already indexes both, so the final state
    of either side will reflect the final fate of the actual column.
    """
    alive = AliveSet()

    for (app, model, field_name), events in timeline.field_events.items():
        ordered = sorted(events, key=lambda e: e.migration_name)
        last = ordered[-1]
        if last.class_name == "RemoveField":
            continue
        alive.fields.add((app, model, field_name))
        # Last AlterField (if any) is the "shape that survives."
        for ev in reversed(ordered):
            if ev.class_name == "AlterField":
                alive.last_alter_per_field[(app, model, field_name)] = ev.migration_name
                break

    for (app, model), events in timeline.model_events.items():
        ordered = sorted(events, key=lambda e: e.migration_name)
        last = ordered[-1]
        if last.class_name == "DeleteModel":
            continue
        alive.models.add((app, model))

    for (app, model, idx_name), events in timeline.index_events.items():
        ordered = sorted(events, key=lambda e: e.migration_name)
        last = ordered[-1]
        if last.class_name == "RemoveIndex":
            continue
        alive.indexes.add((app, model, idx_name))

    return alive


# ---------- op classification ----------


def classify_op(op: dict[str, Any], alive: AliveSet, last_alter: dict[tuple[str, str, str], str]) -> str:
    """Categorize one profiled OpRecord."""
    op_type = op.get("operation_type", "")
    metadata = op.get("metadata") or {}

    if op_type == "__bootstrap__":
        return WasteCategory.BOOTSTRAP

    if op_type == "RunPython":
        return WasteCategory.BACKFILL

    if op.get("is_state_only"):
        return WasteCategory.STATE_ONLY
    if op_type in {"SeparateDatabaseAndState", "AlterModelOptions", "AlterModelManagers", "AlterOrderWithRespectTo"}:
        return WasteCategory.STATE_ONLY

    app = op.get("app_label", "")

    # Field-level ops.
    if op_type in {"AddField", "AlterField"} and metadata.get("model_name") and metadata.get("field_name"):
        key = (app, metadata["model_name"], metadata["field_name"])
        if key not in alive.fields:
            return WasteCategory.DEAD_TARGET
        if op_type == "AddField":
            return WasteCategory.ESSENTIAL_CREATE
        # AlterField against alive field.
        final_alter = last_alter.get(key)
        if final_alter == op.get("migration_name"):
            return WasteCategory.ESSENTIAL_RESHAPE
        return WasteCategory.REDUNDANT_RESHAPE
    if op_type in {"RemoveField"}:
        return WasteCategory.REMOVAL
    if op_type == "RenameField":
        # Treat as essential reshape if either side is alive; otherwise dead.
        old = (app, metadata.get("model_name", ""), metadata.get("old_name", ""))
        new = (app, metadata.get("model_name", ""), metadata.get("new_name", ""))
        if new in alive.fields or old in alive.fields:
            return WasteCategory.ESSENTIAL_RESHAPE
        return WasteCategory.DEAD_TARGET

    # Model-level ops.
    if op_type in {"CreateModel"} and metadata.get("model_name"):
        key = (app, metadata["model_name"])
        return WasteCategory.ESSENTIAL_CREATE if key in alive.models else WasteCategory.DEAD_TARGET
    if op_type == "DeleteModel":
        return WasteCategory.REMOVAL
    if op_type == "RenameModel":
        # If either old or new name is alive, the rename matters.
        return WasteCategory.ESSENTIAL_RESHAPE

    if op_type in {"AlterModelTable", "AlterUniqueTogether", "AlterIndexTogether"}:
        # Hard to attribute cheaply — treat as essential reshape if model alive.
        if metadata.get("model_name") and (app, metadata["model_name"]) in alive.models:
            return WasteCategory.ESSENTIAL_RESHAPE
        return WasteCategory.DEAD_TARGET

    # Index / constraint ops.
    if op_type in {"AddIndex", "AddIndexConcurrently"} and metadata.get("model_name"):
        idx_name = metadata.get("index_name")
        if idx_name and (app, metadata["model_name"], idx_name) in alive.indexes:
            return WasteCategory.ESSENTIAL_CREATE
        return WasteCategory.DEAD_TARGET
    if op_type in {"RemoveIndex", "RemoveIndexConcurrently", "RenameIndex"}:
        return WasteCategory.REMOVAL
    if op_type == "AddConstraint":
        # Constraint-name tracking isn't in the alive set yet — treat as essential
        # if the model is alive, otherwise dead.
        if metadata.get("model_name") and (app, metadata["model_name"]) in alive.models:
            return WasteCategory.ESSENTIAL_CREATE
        return WasteCategory.DEAD_TARGET
    if op_type in {"RemoveConstraint", "AlterConstraint", "AddConstraintNotValid", "ValidateConstraint"}:
        return WasteCategory.ESSENTIAL_RESHAPE  # best-effort

    if op_type == "RunSQL":
        # RunSQL is opaque — assume essential unless evidence suggests otherwise.
        return WasteCategory.ESSENTIAL_RESHAPE

    return WasteCategory.UNKNOWN


# ---------- breakdown ----------


@dataclass
class WasteBreakdown:
    """Aggregated waste analysis for the whole run."""

    sql_ms_by_category: dict[str, float] = field(default_factory=dict)
    op_count_by_category: dict[str, int] = field(default_factory=dict)
    # State-machine overhead split.
    state_machine_essential_ms: float = 0.0
    state_machine_avoidable_ms: float = 0.0
    apply_total_ms: float = 0.0
    sql_total_ms: float = 0.0

    # Projected Migration.apply wall-clock for a fully squashed initial
    # against the current schema. Either calibrated from per-state-op data
    # when state_op records are available, or falls back to the conservative
    # 5s constant. See `_project_full_squash_floor_ms`.
    one_migration_apply_floor_ms: float = 5000.0
    # When calibrated, how it was computed (for the report).
    one_migration_apply_floor_basis: str = "hardcoded conservative default (5.0s)"

    @property
    def avoidable_sql_ms(self) -> float:
        return sum(ms for cat, ms in self.sql_ms_by_category.items() if cat in AVOIDABLE_CATEGORIES)

    @property
    def essential_sql_ms(self) -> float:
        return sum(ms for cat, ms in self.sql_ms_by_category.items() if cat not in AVOIDABLE_CATEGORIES)

    @property
    def state_machine_total_ms(self) -> float:
        return self.state_machine_essential_ms + self.state_machine_avoidable_ms

    @property
    def amortizable_state_machine_ms(self) -> float:
        """The portion of state-machine cost that would vanish under one
        mega-squash (all migrations collapsed). The floor is one Migration.apply's
        worth of state-rebuild for the final schema."""
        return max(self.state_machine_total_ms - self.one_migration_apply_floor_ms, 0.0)

    @property
    def total_avoidable_ms(self) -> float:
        """Aggressive avoidable: SQL waste + ALL state-machine cost above the
        one-migration floor. This is the right number for someone asking
        'what's the floor if we restart from scratch?'."""
        return self.avoidable_sql_ms + self.amortizable_state_machine_ms

    @property
    def theoretical_floor_ms(self) -> float:
        """Essential SQL + one Migration.apply of state-rebuild."""
        return self.essential_sql_ms + min(self.state_machine_total_ms, self.one_migration_apply_floor_ms)

    @property
    def avoidable_share(self) -> float:
        return self.total_avoidable_ms / self.apply_total_ms if self.apply_total_ms else 0.0


def _project_full_squash_floor_ms(state_ops: list[dict[str, Any]], alive: AliveSet) -> tuple[float, str]:
    """Calibrate the cost of one Migration.apply for a fully squashed initial.

    Uses the observed average cost per state_forwards call from existing
    squashed initials in this run (where the registry grows from empty),
    multiplied by the projected number of state ops in a full re-squash.

    The growing-registry regime matters: in late history, an AlterField on a
    700-model registry takes ~150ms because reload_model walks the relation
    graph. In an initial squash, the same model class gets one CreateModel
    against a smaller registry — typically ~25ms in our observed squash.
    Projecting one against the other gives a much better floor than a
    flat 5s constant.

    Falls back to a 5s default if no existing squash is present in the run
    (i.e., on a project without any squashed migrations yet).
    """
    if not state_ops:
        return 5000.0, "no state_op records — hardcoded default (5.0s)"

    # Identify existing squashed initials by their migration name (Django's
    # `squashmigrations` convention is e.g. `0001_initial_squashed_0284_...`).
    # Use the largest-by-op-count one as the calibration basis.
    state_ops_by_mig: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for so in state_ops:
        state_ops_by_mig[(so["app_label"], so["migration_name"])].append(so)

    squash_ops: list[dict[str, Any]] = []
    chosen_name: str | None = None
    for (app, name), ops in state_ops_by_mig.items():
        if "squashed" not in name:
            continue
        if len(ops) > len(squash_ops):
            squash_ops = ops
            chosen_name = f"{app}.{name}"

    if not squash_ops:
        return 5000.0, "no existing `*_squashed_*` migration to calibrate against — hardcoded default (5.0s)"

    # Average cost per state_forwards call in the existing squash. This is
    # the "growing registry" regime per-op cost we want to extrapolate from.
    avg_per_op_ms = sum(so["duration_ms"] for so in squash_ops) / len(squash_ops)

    # Project the number of state ops a full re-squash would have. After
    # Django's MigrationOptimizer runs, the optimized initial typically has
    # one CreateModel per alive model (fields baked in) + one AddIndex per
    # alive index. Other state ops (AlterUniqueTogether, AddConstraint) are
    # rarer; the empirical fudge (×1.15) reflects their contribution in
    # existing squashes.
    projected_op_count = int((len(alive.models) + len(alive.indexes)) * 1.15)
    if projected_op_count == 0:
        return 5000.0, "alive set is empty — hardcoded default (5.0s)"

    projected_floor_ms = projected_op_count * avg_per_op_ms
    basis = (
        f"calibrated from {chosen_name} ({len(squash_ops)} state ops at "
        f"{avg_per_op_ms:.1f}ms avg), projected over {projected_op_count} ops "
        f"({len(alive.models)} alive models + {len(alive.indexes)} alive indexes × 1.15)"
    )
    return projected_floor_ms, basis


def compute_waste_breakdown(
    profile_ops: list[dict[str, Any]],
    migration_summaries: dict[tuple[str, str], float],
    alive: AliveSet,
    state_ops: list[dict[str, Any]] | None = None,
) -> WasteBreakdown:
    """Aggregate per-op and per-migration waste."""
    sql_by_cat: dict[str, float] = defaultdict(float)
    count_by_cat: dict[str, int] = defaultdict(int)

    # Track per-migration: total SQL time + max-category-of-its-ops (for
    # attributing state-machine overhead).
    per_mig_sql: dict[tuple[str, str], float] = defaultdict(float)
    per_mig_has_essential: dict[tuple[str, str], bool] = defaultdict(bool)

    for op in profile_ops:
        cat = classify_op(op, alive, alive.last_alter_per_field)
        sql_by_cat[cat] += op["duration_ms"]
        count_by_cat[cat] += 1
        key = (op["app_label"], op["migration_name"])
        per_mig_sql[key] += op["duration_ms"]
        if cat in {WasteCategory.ESSENTIAL_CREATE, WasteCategory.ESSENTIAL_RESHAPE}:
            per_mig_has_essential[key] = True

    apply_total_ms = sum(migration_summaries.values())
    sql_total_ms = sum(sql_by_cat.values())

    # State-machine portion of each migration = its apply_total minus the sum
    # of its operations' SQL time. Attribute the per-migration state-machine
    # cost to "essential" if any of its ops are essential, else "avoidable".
    state_essential = 0.0
    state_avoidable = 0.0
    for (app, name), apply_ms in migration_summaries.items():
        sql_ms = per_mig_sql.get((app, name), 0.0)
        state_ms = max(apply_ms - sql_ms, 0.0)
        if per_mig_has_essential.get((app, name), False):
            state_essential += state_ms
        else:
            state_avoidable += state_ms

    floor_ms, floor_basis = _project_full_squash_floor_ms(state_ops or [], alive)

    return WasteBreakdown(
        sql_ms_by_category=dict(sql_by_cat),
        op_count_by_category=dict(count_by_cat),
        state_machine_essential_ms=state_essential,
        state_machine_avoidable_ms=state_avoidable,
        apply_total_ms=apply_total_ms,
        sql_total_ms=sql_total_ms,
        one_migration_apply_floor_ms=floor_ms,
        one_migration_apply_floor_basis=floor_basis,
    )
