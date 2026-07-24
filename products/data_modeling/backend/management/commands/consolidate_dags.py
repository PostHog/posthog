import uuid
import dataclasses
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import delete_schedule

from products.data_modeling.backend.logic.cohort_scheduling import is_tier_schedule_id
from products.data_modeling.backend.logic.freshness import (
    STREAMING,
    all_source_floors,
    format_cadence,
    normalize_seed_target,
)
from products.data_modeling.backend.logic.node_frequency import (
    build_frequency_graph,
    get_declared_target,
    schedulable_nodes,
    set_declared_target,
)
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.logic.schedule_reconcile import (
    delete_v1_saved_query_schedules,
    list_existing_schedule_ids,
    null_saved_query_intervals,
    reconcile_dag_schedules,
)
from products.data_modeling.backend.models.dag import DAG, DEFAULT_DAG_NAME
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

logger = structlog.get_logger(__name__)

# How the target DAG is currently scheduled — decides which Temporal work is safe.
MODE_TIERED = "tiered"  # per-cadence tier schedules ({dag_id}:{seconds})
MODE_LEGACY_V2 = "legacy-v2"  # single whole-DAG execute-dag schedule (id == dag_id)
MODE_V1 = "v1-only"  # no execute-dag schedule; queries run on per-query v1 schedules


@dataclasses.dataclass
class MoveItem:
    saved_query: DataWarehouseSavedQuery
    declared_target: timedelta | None


@dataclasses.dataclass
class DropItem:
    saved_query_id: str
    node_id: str
    name: str
    declared_target: timedelta | None


@dataclasses.dataclass
class SourceDagPlan:
    dag: DAG
    moves: list[MoveItem]  # dependency (topological) order
    drops: list[DropItem]
    moved_node_ids: set[str]  # kept for the dry run's edge-impact count
    dropped_node_ids: set[str]


class Command(BaseCommand):
    help = (
        "Plan and (with --apply) execute collapsing a team's overlapping DAGs into one. The dry run "
        "is the planner: it partitions each source DAG's nodes into MOVE/DROP, counts the edges a "
        "merge would re-point or dedup, flags saved queries whose declared freshness targets differ "
        "between copies (a 'which cadence wins?' call for a human), and checks for anomalous "
        "cross-DAG edges. For every non-managed source DAG, saved queries already in the "
        "target are dropped (their duplicate node dies with the source DAG) and the rest are moved "
        "by re-syncing them into the target in dependency order, then the source DAG is deleted "
        "(cascading its nodes and edges). Tears down the source DAGs' execute-dag schedules, then "
        "finalizes the target from its persistent state: seed declared targets from leftover v1 "
        "intervals, sweep v1 per-query schedules, null the intervals, reconcile tiers once. "
        "Because the finalize derives from the target rather than this run's moves, re-running "
        "with --apply completes a partially-applied consolidation. Dry run by default; pass "
        "--apply to execute."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--target-dag-id",
            type=str,
            default=None,
            help="Force the merge target DAG (default: the canonical 'Default' DAG, else the largest)",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Execute the consolidation. Without this flag the command is a dry run and changes nothing.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="List per-query names under each source DAG's move/drop counts (default: counts only)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        apply_changes: bool = options["apply"]
        all_dags = list(DAG.objects.filter(team_id=team_id))
        if not all_dags:
            raise CommandError(f"Team {team_id} has no DAGs")

        # System-managed DAGs (Revenue Analytics) are never consolidated: the managed viewset
        # re-asserts its nodes' placement on every sync, so a move out is silently undone, and
        # syncing a query into a managed DAG is refused outright. Exclude them as source and target.
        managed_dags = [dag for dag in all_dags if dag.is_managed]
        dags = [dag for dag in all_dags if not dag.is_managed]

        forced_id: str | None = options["target_dag_id"]
        if forced_id:
            try:
                forced_uuid = uuid.UUID(forced_id)
            except ValueError:
                raise CommandError(f"--target-dag-id must be a UUID, got {forced_id!r}")
            if any(dag.id == forced_uuid for dag in managed_dags):
                raise CommandError(f"--target-dag-id {forced_id} is a system-managed DAG and cannot be a merge target")

        if not dags:
            raise CommandError(f"Team {team_id} has no non-managed DAGs to consolidate")

        target = self._pick_target(dags, forced_id)
        source_dags = sorted((dag for dag in dags if dag.id != target.id), key=lambda d: d.name)

        self.stdout.write(f"\nTeam {team_id} — {len(dags)} DAG(s)")
        if managed_dags:
            excluded = ", ".join(f"{dag.name} ({dag.id})" for dag in managed_dags)
            self.stdout.write(f"Excluding {len(managed_dags)} system-managed DAG(s): {excluded}")
        self.stdout.write(f"Merge target: {target.name} ({target.id}) — {self._target_reason(target, options)}")

        plans = self._build_plan(target, source_dags)
        self._print_plan(target, plans, team_id=team_id, dags=dags, verbose=options["verbose"])

        if not apply_changes:
            self.stdout.write(
                "\n(dry run — nothing was changed; target schedule mode is detected at apply time; "
                "pass --apply to execute)"
            )
            return

        if not settings.TEST:
            confirm = input(
                f"\n\tWill consolidate {len(source_dags)} source DAG(s) into {target.name} ({target.id}) "
                f"for team {team_id}, deleting the source DAGs. Proceed? (y/n) "
            )
            if confirm.strip().lower() != "y":
                self.stdout.write("Aborting")
                return

        # Connect before mutating anything: schedule teardown is mandatory once DAGs start moving,
        # so a Temporal outage must abort the run while it is still a pure no-op.
        try:
            temporal = sync_connect()
        except Exception as error:
            raise CommandError(f"Cannot connect to Temporal, aborting before any change: {error}")
        mode = self._detect_target_mode(self._list_dag_schedules_or_abort(str(target.id)))
        self.stdout.write(f"\nTarget schedule mode: {mode}")
        if mode == MODE_V1:
            # A v2-scheduled source would strand its queries: its execute-dag schedules die with
            # the source DAG, but a v1-only target has no schedule to hand coverage to.
            v2_sources = [
                f"{plan.dag.name} ({plan.dag.id})"
                for plan in plans
                if self._list_dag_schedules_or_abort(str(plan.dag.id))
            ]
            if v2_sources:
                raise CommandError(
                    f"target {target.name} ({target.id}) is v1-only but source(s) "
                    f"{', '.join(v2_sources)} are v2-scheduled — migrate the target to tiers first "
                    "via reconcile_freshness_schedules, or choose a tiered target"
                )
            self.stdout.write(
                "  target has no execute-dag schedule and every source is v1-only — graph-only "
                "consolidation: v1 per-query schedules and sync intervals are kept so the moved "
                "queries stay scheduled"
            )

        consolidated_sq_ids: set[str] = set()
        kept_dags: list[str] = []
        for plan in plans:
            kept_reason = self._apply_source_dag(plan, target, temporal, consolidated_sq_ids)
            if kept_reason:
                kept_dags.append(f"{plan.dag.name} ({plan.dag.id}): {kept_reason}")

        v1_failed_sq_ids = self._finalize_target(target, temporal, mode)

        self.stdout.write(f"\nDone: consolidated {len(consolidated_sq_ids)} saved query(ies) into {target.name}")
        if v1_failed_sq_ids:
            self.stdout.write(
                self.style.WARNING(
                    f"  v1 schedule delete failed for {len(v1_failed_sq_ids)} saved query(ies) "
                    f"(intervals kept for retry): {', '.join(sorted(v1_failed_sq_ids))}"
                )
            )
        if kept_dags:
            for line in kept_dags:
                self.stdout.write(self.style.ERROR(f"  kept source DAG {line}"))
            raise CommandError(
                f"consolidation incomplete: {len(kept_dags)} source DAG(s) kept; "
                "resolve the failures above and re-run (the command converges on re-run)"
            )

    def _pick_target(self, dags: list[DAG], target_dag_id: str | None) -> DAG:
        if target_dag_id:
            try:
                wanted = uuid.UUID(target_dag_id)
            except ValueError:
                raise CommandError(f"--target-dag-id must be a UUID, got {target_dag_id!r}")
            for dag in dags:
                if dag.id == wanted:
                    return dag
            raise CommandError(f"--target-dag-id {target_dag_id} is not a DAG of this team")

        for dag in dags:
            if dag.name == DEFAULT_DAG_NAME:
                return dag

        counts: dict[Any, int] = defaultdict(int)
        for dag_id in Node.objects.filter(dag__in=dags).values_list("dag_id", flat=True):
            counts[dag_id] += 1
        return sorted(dags, key=lambda d: (-counts.get(d.id, 0), d.name))[0]

    def _target_reason(self, target: DAG, options: dict[str, Any]) -> str:
        if options["target_dag_id"]:
            return "chosen via --target-dag-id"
        if target.name == DEFAULT_DAG_NAME:
            return "canonical 'Default' DAG"
        return "no Default DAG — largest DAG by node count"

    def _build_plan(self, target: DAG, source_dags: list[DAG]) -> list[SourceDagPlan]:
        """Partition every source DAG's schedulable nodes into MOVE/DROP and
        topologically order the moves, all read-only so any cycle aborts before a single mutation.
        """
        target_sq_ids = {str(sq_id) for sq_id in schedulable_nodes(target).values_list("saved_query_id", flat=True)}
        claimed: set[str] = set()  # saved queries a preceding source DAG already moves
        plans: list[SourceDagPlan] = []
        for dag in source_dags:
            moves_by_node: dict[str, MoveItem] = {}
            drops: list[DropItem] = []
            for node in schedulable_nodes(dag).select_related("saved_query"):
                saved_query = node.saved_query
                if saved_query is None:
                    continue
                sq_id = str(saved_query.id)
                declared = get_declared_target(node)
                if sq_id in target_sq_ids or sq_id in claimed:
                    drops.append(
                        DropItem(saved_query_id=sq_id, node_id=str(node.id), name=node.name, declared_target=declared)
                    )
                else:
                    moves_by_node[str(node.id)] = MoveItem(saved_query=saved_query, declared_target=declared)
                    claimed.add(sq_id)
            order = self._dependency_order(dag, set(moves_by_node))
            plans.append(
                SourceDagPlan(
                    dag=dag,
                    moves=[moves_by_node[node_id] for node_id in order],
                    drops=drops,
                    moved_node_ids=set(moves_by_node),
                    dropped_node_ids={drop.node_id for drop in drops},
                )
            )
        return plans

    def _dependency_order(self, dag: DAG, node_ids: set[str]) -> list[str]:
        """Kahn's algorithm over the source DAG's edges restricted to the moved nodes: a moved
        query's node must exist in the target before a moved dependent's sync resolves it. The
        model forbids cycles, but a corrupt graph must abort here, before anything is mutated.
        """
        children: dict[str, list[str]] = defaultdict(list)
        in_degree = dict.fromkeys(node_ids, 0)
        for source_id, target_id in Edge.objects.filter(dag=dag).values_list("source_id", "target_id"):
            src, tgt = str(source_id), str(target_id)
            if src in node_ids and tgt in node_ids:
                children[src].append(tgt)
                in_degree[tgt] += 1
        queue = deque(sorted(node_id for node_id, degree in in_degree.items() if degree == 0))
        order: list[str] = []
        while queue:
            node_id = queue.popleft()
            order.append(node_id)
            for child in children[node_id]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        if len(order) != len(node_ids):
            raise CommandError(f"cycle detected among nodes to move in DAG {dag.id}; aborting before any change")
        return order

    def _print_plan(
        self, target: DAG, plans: list[SourceDagPlan], *, team_id: int, dags: list[DAG], verbose: bool
    ) -> None:
        if not plans:
            self.stdout.write("  Only one DAG — nothing to consolidate.")
            return
        total_moved = 0
        total_dropped = 0
        total_repoint_edges = 0
        total_dedup_edges = 0
        for plan in plans:
            total_moved += len(plan.moves)
            total_dropped += len(plan.drops)
            repoint, dedup = self._count_edge_impact(plan.dag, plan.moved_node_ids, plan.dropped_node_ids)
            total_repoint_edges += repoint
            total_dedup_edges += dedup
            self.stdout.write(f"\n  Source DAG {plan.dag.name} ({plan.dag.id}):")
            self.stdout.write(f"    move {len(plan.moves)}, drop {len(plan.drops)}")
            self.stdout.write(f"    edges to re-point (touch a moved node): {repoint}")
            self.stdout.write(f"    edges to drop as redundant (only dropped nodes): {dedup}")
            self.stdout.write(
                f"    v1 schedules swept in the target-wide finalize (if target is v2-scheduled): "
                f"{len(plan.moves) + len(plan.drops)}"
            )
            self.stdout.write(f"    execute-dag schedules to tear down: all listed for DAG {plan.dag.id}")
            if verbose:
                if plan.moves:
                    move_names = ", ".join(item.saved_query.name for item in plan.moves)
                    self.stdout.write(f"      move (in dependency order): {move_names}")
                if plan.drops:
                    self.stdout.write(f"      drop: {', '.join(sorted(drop.name for drop in plan.drops))}")

        conflicts = self._find_target_conflicts(dags)
        self._print_conflicts(conflicts)
        cross_dag_edges = self._count_cross_dag_edges(team_id)

        target_after = schedulable_nodes(target).count() + total_moved
        self.stdout.write(f"\nSummary for target {target.name} ({target.id}):")
        self.stdout.write(f"  nodes in target after merge: {target_after}")
        self.stdout.write(f"  moved: {total_moved}, dropped: {total_dropped}")
        self.stdout.write(f"  edges to re-point: {total_repoint_edges}, edges to drop: {total_dedup_edges}")
        self.stdout.write(f"  source DAGs to delete: {len(plans)}")
        self.stdout.write(f"  freshness-target conflicts: {len(conflicts)}")
        if cross_dag_edges:
            self.stdout.write(self.style.WARNING(f"  ⚠ anomalous cross-DAG edges found: {cross_dag_edges}"))
        else:
            self.stdout.write("  cross-DAG edges: 0 (edges are within-DAG by construction)")
        self.stdout.write("  target reconciled once at the end (if on cadence tiers)")

    def _count_edge_impact(self, dag: DAG, moved_ids: set[str], dropped_ids: set[str]) -> tuple[int, int]:
        """Count edges a real merge would touch. Edges are within-DAG (source/target/edge all share
        the DAG), so an edge touching a moved node must be re-pointed to the target DAG; an edge
        whose only involved nodes are dropped is redundant against the target's existing edge.
        """
        repoint = 0
        dedup = 0
        for source_id, target_id in Edge.objects.filter(dag=dag).values_list("source_id", "target_id"):
            src, tgt = str(source_id), str(target_id)
            if src in moved_ids or tgt in moved_ids:
                repoint += 1
            elif src in dropped_ids or tgt in dropped_ids:
                dedup += 1
        return repoint, dedup

    def _find_target_conflicts(self, dags: list[DAG]) -> list[tuple[str, list[tuple[str, timedelta | None]]]]:
        """Saved queries with schedulable nodes in 2+ DAGs whose declared freshness targets differ.
        A conflict is 2+ distinct non-None declared targets across the copies — after a merge only
        one node survives, so a human must pick the winning cadence. All-unset or agreeing targets
        are not conflicts (unset means 'no opinion', so a lone declared target wins cleanly).
        """
        by_saved_query: dict[object, list[tuple[str, str, timedelta | None]]] = defaultdict(list)
        dag_names = {dag.id: dag.name for dag in dags}
        for node in Node.objects.filter(dag__in=dags).exclude(type=NodeType.TABLE).exclude(saved_query__deleted=True):
            if node.saved_query_id is None:
                continue
            by_saved_query[node.saved_query_id].append((dag_names[node.dag_id], node.name, get_declared_target(node)))

        conflicts: list[tuple[str, list[tuple[str, timedelta | None]]]] = []
        for copies in by_saved_query.values():
            if len(copies) < 2:
                continue
            declared = {target for _dag_name, _query_name, target in copies if target is not None}
            if len(declared) < 2:
                continue
            query_name = copies[0][1]
            copies_report = sorted((dag_name, target) for dag_name, _query_name, target in copies)
            conflicts.append((query_name, copies_report))
        return sorted(conflicts, key=lambda c: c[0])

    def _print_conflicts(self, conflicts: list[tuple[str, list[tuple[str, timedelta | None]]]]) -> None:
        self.stdout.write("\nFreshness-target conflicts (which cadence wins after merge?):")
        if not conflicts:
            self.stdout.write("  none")
            return
        for query_name, copies in conflicts:
            self.stdout.write(self.style.WARNING(f"  ⚠ {query_name}:"))
            for dag_name, target in copies:
                label = format_cadence(target) if target is not None else "unset"
                self.stdout.write(f"      {dag_name}: {label}")

    def _count_cross_dag_edges(self, team_id: int) -> int:
        """Defensive check: edges whose endpoints' DAGs disagree with the edge's own DAG. The model
        forbids these, so a non-zero count means data corruption worth surfacing before any merge.
        """
        node_dags = dict(Node.objects.filter(team_id=team_id).values_list("id", "dag_id"))
        anomalies = 0
        for source_id, target_id, dag_id in Edge.objects.filter(team_id=team_id).values_list(
            "source_id", "target_id", "dag_id"
        ):
            if node_dags.get(source_id) != dag_id or node_dags.get(target_id) != dag_id:
                anomalies += 1
        return anomalies

    def _list_dag_schedules_or_abort(self, dag_id: str) -> set[str]:
        """Authoritative listing of a DAG's execute-dag schedule ids via the PostHogDagId search
        attribute — never guessed from an id formula, so off-scheme schedules can't escape. Only
        used before the first mutation, where aborting is still a pure no-op.
        """
        try:
            return list_existing_schedule_ids(dag_id)
        except Exception as error:
            raise CommandError(f"Cannot list Temporal schedules for DAG {dag_id}, aborting before any change: {error}")

    def _detect_target_mode(self, target_schedule_ids: set[str]) -> str:
        if any(is_tier_schedule_id(schedule_id) for schedule_id in target_schedule_ids):
            return MODE_TIERED
        if target_schedule_ids:
            return MODE_LEGACY_V2
        return MODE_V1

    def _apply_source_dag(
        self,
        plan: SourceDagPlan,
        target: DAG,
        temporal: Client,
        consolidated_sq_ids: set[str],
    ) -> str | None:
        """Consolidate one source DAG. Returns None on success, or the reason the DAG was kept.

        Ordering, chosen so a crash at any point leaves a state a re-run converges from:
        1. (DB) sync each MOVE query into the target in dependency order — a crash here leaves
           duplicates the re-run classifies as DROP.
        2. (Temporal) delete the source DAG's execute-dag schedules, from an authoritative
           listing — idempotent, so a crash after this is retried harmlessly.
        3. (DB) delete the source DAG row, cascading its nodes and edges. This must come LAST:
           the row is the only durable pointer to the DAG's Temporal schedules, so deleting it
           before the teardown succeeded would orphan schedules forever.
        The consolidated queries' v1 schedules are swept afterwards by the target-wide finalize,
        which re-runs derive from the target's persistent state.
        """
        self.stdout.write(f"\n  Source DAG {plan.dag.name} ({plan.dag.id}):")
        failed_moves: list[str] = []
        moved_sq_ids: list[str] = []
        for item in plan.moves:
            try:
                node = sync_saved_query_to_dag(item.saved_query, dag=target, reconcile=False)
            except Exception as error:
                failed_moves.append(item.saved_query.name)
                logger.exception(
                    "Failed to move saved query into target DAG",
                    saved_query_id=str(item.saved_query.id),
                    source_dag_id=str(plan.dag.id),
                    target_dag_id=str(target.id),
                )
                self.stderr.write(f"    FAILED to move {item.saved_query.name}: {error}")
                continue
            if node is not None:
                self._carry_declared_target(node, item.declared_target, item.saved_query.name)
            moved_sq_ids.append(str(item.saved_query.id))
            self.stdout.write(f"    moved {item.saved_query.name}")
        for drop in plan.drops:
            node = Node.objects.filter(dag=target, saved_query_id=drop.saved_query_id).first()
            if node is not None:
                self._carry_declared_target(node, drop.declared_target, drop.name)
            self.stdout.write(f"    dropped duplicate {drop.name}")

        if failed_moves:
            # The successful moves are now duplicates a re-run classifies as DROP; deleting the DAG
            # here would destroy the only node of every query that failed to move.
            return f"{len(failed_moves)} move(s) failed ({', '.join(failed_moves)})"

        if not self._teardown_execute_dag_schedules(temporal, str(plan.dag.id)):
            return "execute-dag schedule teardown failed; DAG kept so a re-run can retry it"

        plan.dag.delete()
        self.stdout.write(f"    deleted source DAG {plan.dag.id}")
        consolidated_sq_ids.update(moved_sq_ids)
        consolidated_sq_ids.update(drop.saved_query_id for drop in plan.drops)
        return None

    def _carry_declared_target(self, node: Node, declared: timedelta | None, name: str) -> None:
        """Carry a source node's declared freshness target onto its target-DAG node. The target
        DAG's copy wins a disagreement (the dry run surfaces these conflicts for a human first).
        """
        if declared is None:
            return
        existing = get_declared_target(node)
        if existing is None:
            set_declared_target(node, declared)
        elif existing != declared:
            self.stdout.write(
                f"    cadence conflict on {name}: keeping target's {format_cadence(existing)} "
                f"(source declared {format_cadence(declared)})"
            )

    def _teardown_execute_dag_schedules(self, temporal: Client, dag_id: str) -> bool:
        """Delete the execute-dag schedules Temporal actually has for this DAG, from an
        authoritative listing (PostHogDagId search attribute) rather than an id formula, so an
        off-scheme schedule cannot be orphaned by the DAG's deletion. NOT_FOUND means a concurrent
        delete won the race; a listing or delete failure keeps the DAG for a re-run.
        """
        try:
            schedule_ids = list_existing_schedule_ids(dag_id)
        except Exception:
            logger.exception("Failed to list execute-dag schedules", dag_id=dag_id)
            self.stderr.write(f"    FAILED to list execute-dag schedules for DAG {dag_id}")
            return False
        ok = True
        for schedule_id in sorted(schedule_ids):
            try:
                delete_schedule(temporal, schedule_id=schedule_id)
                self.stdout.write(f"    deleted execute-dag schedule {schedule_id}")
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    ok = False
                    logger.exception("Failed to delete execute-dag schedule", schedule_id=schedule_id)
                    self.stderr.write(f"    FAILED to delete execute-dag schedule {schedule_id}")
            except Exception:
                ok = False
                logger.exception("Failed to delete execute-dag schedule", schedule_id=schedule_id)
                self.stderr.write(f"    FAILED to delete execute-dag schedule {schedule_id}")
        return ok

    def _finalize_target(self, target: DAG, temporal: Client, mode: str) -> set[str]:
        """Converge the target after the moves: seed declared targets from leftover v1 intervals,
        sweep the v1 per-query schedules, null the consumed intervals, and reconcile the tier
        schedules once. Everything here derives from the target's persistent state — never this
        run's move list — so re-running the command completes a consolidation a crash left
        half-finished; that re-run IS the recovery mechanism, at the cost of a no-op run
        re-sweeping and re-reconciling the target.

        On a legacy-v2 target the whole-DAG schedule (node_ids=None) picks the moved nodes up
        automatically, so only tiered targets are reconciled; the seeded declared targets preserve
        cadence intent for the eventual tier conversion either way. On a v1-only target nothing
        runs — every source was verified v1-only before any mutation, so the kept v1 schedules and
        intervals keep the moved queries scheduled. Returns the saved-query ids whose v1 delete
        failed (their intervals are kept as the retry signal).
        """
        if mode not in (MODE_TIERED, MODE_LEGACY_V2):
            return set()
        self._seed_targets_from_intervals(target)
        nodes = list(schedulable_nodes(target).select_related("saved_query"))
        v1_failed = delete_v1_saved_query_schedules(
            nodes, team_id=target.team_id, dag_id=str(target.id), temporal=temporal
        )
        swept_ids = {str(node.saved_query_id) for node in nodes if node.saved_query_id is not None} - v1_failed
        cleared = null_saved_query_intervals(target, only_saved_query_ids=swept_ids)
        self.stdout.write(
            f"\n  swept v1 schedules for {len(nodes)} saved query(ies) ({len(v1_failed)} failed), "
            f"cleared sync_frequency_interval on {cleared}"
        )
        if mode == MODE_TIERED:
            try:
                reconcile_dag_schedules(target, require_tiered=True)
                self.stdout.write(f"  reconciled target DAG {target.id} tier schedules")
            except Exception as error:
                logger.exception("Failed to reconcile target DAG after consolidation", dag_id=str(target.id))
                raise CommandError(
                    f"consolidation applied but the final reconcile of target {target.id} failed ({error}); "
                    "run reconcile_freshness_schedules for this team to converge the tier schedules"
                )
        return v1_failed

    def _seed_targets_from_intervals(self, target: DAG) -> None:
        """A query about to lose its v1 sync_frequency_interval must not lose its cadence intent:
        seed each target-DAG node's declared target from its query's interval (normalized, never
        overwriting) before the interval is nulled — persist_seed_targets/convert_dag_to_tiers in
        spirit, scoped to the target DAG and idempotent so crash-recovery re-runs converge.
        """
        graph = build_frequency_graph(target)
        floors = all_source_floors(graph.edges, graph.source_intervals)
        for node in schedulable_nodes(target).select_related("saved_query"):
            saved_query = node.saved_query
            if saved_query is None or saved_query.sync_frequency_interval is None:
                continue
            if get_declared_target(node) is not None:
                continue
            seed = normalize_seed_target(saved_query.sync_frequency_interval, floors.get(str(node.id), STREAMING))
            set_declared_target(node, seed)
