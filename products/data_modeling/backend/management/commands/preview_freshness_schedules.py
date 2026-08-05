import uuid
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from products.data_modeling.backend.logic.freshness import format_cadence
from products.data_modeling.backend.logic.schedule_reconcile import DagSchedulePreview, preview_dag_schedules
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node, NodeType


class Command(BaseCommand):
    help = (
        "Dry-run: show the per-cadence-tier schedules a DAG would get from its nodes' freshness "
        "targets, and the create/update/delete plan against its current schedules. Reads only — "
        "never creates, updates, or deletes a schedule, and touches no live read/write path. "
        "Prints a compact summary by default (--verbose for per-node cadences), plus a team-level "
        "cross-DAG duplication report to judge whether a redundant DAG is safe to drop."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--dag-id", type=str, default=None, help="Limit to one DAG (default: all of the team's)")
        parser.add_argument(
            "--seed",
            action="store_true",
            help="Model the go-live plan: seed a target from current cadence for nodes without one (in memory, no write)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print every node's effective cadence and each tier's members (default: tier counts only)",
        )

    def handle(self, *args, **options):
        queryset = DAG.objects.filter(team_id=options["team_id"])
        if options["dag_id"]:
            try:
                queryset = queryset.filter(id=uuid.UUID(options["dag_id"]))
            except ValueError:
                raise CommandError(f"--dag-id must be a UUID, got {options['dag_id']!r}")
        dags = list(queryset)
        if not dags:
            raise CommandError("No matching DAGs")
        for dag in dags:
            self._preview(dag, seed=options["seed"], verbose=options["verbose"])
        self._print_cross_dag_duplication(options["team_id"])
        self.stdout.write("\n(dry run — no schedules were created, updated, or deleted)")

    def _preview(self, dag: DAG, *, seed: bool, verbose: bool) -> None:
        preview = preview_dag_schedules(dag, seed=seed)
        names = {str(node_id): name for node_id, name in Node.objects.filter(dag=dag).values_list("id", "name")}

        seeded_note = "  [seeded]" if preview.seeded else ""
        self.stdout.write(f"\nDAG {dag.name} ({dag.id}) — team {dag.team_id}{seeded_note}")

        tiers = "  ".join(
            f"{format_cadence(interval)} x{len(node_ids)}"
            for interval, node_ids in sorted(preview.desired_tiers.items())
        )
        unscheduled = sum(1 for cadence in preview.effective.values() if cadence is None)
        tier_line = tiers or "(none)"
        if unscheduled:
            tier_line += f"  unscheduled x{unscheduled}"
        self.stdout.write(f"  tiers: {tier_line}")

        plan = preview.plan
        self.stdout.write(
            f"  plan: CREATE {len(plan.to_create)}, UPDATE {len(plan.to_update)}, DELETE {len(plan.to_delete)}"
        )

        self._print_warnings(preview, names)

        if verbose:
            self._print_verbose(preview, names)

    def _print_warnings(self, preview: DagSchedulePreview, names: dict[str, str]) -> None:
        wrote = False
        for clamp in sorted(preview.clamped, key=lambda c: names.get(c.node_id, c.node_id)):
            wrote = True
            self.stdout.write(
                f"  ⚠ clamp: {names.get(clamp.node_id, clamp.node_id)} demanded every {clamp.demanded} "
                f"but its sources only deliver every {clamp.source_floor} → will run {clamp.clamped_to}"
            )
        for interval in preview.unsupported_tiers:
            wrote = True
            self.stdout.write(f"  ⚠ unsupported tier: {interval} is not a schedulable bucket — reconcile would refuse")
        for invalid in sorted(preview.invalid_targets, key=lambda t: names.get(t.node_id, t.node_id)):
            wrote = True
            ceiling = str(invalid.consumer_ceiling) if invalid.consumer_ceiling is not None else "none"
            self.stdout.write(
                f"  ⚠ invalid declared target: {names.get(invalid.node_id, invalid.node_id)} declares "
                f"{invalid.declared} but its legal range is [{invalid.source_floor} … {ceiling}]"
            )
        if preview.best_effort_source_ids:
            wrote = True
            flagged = ", ".join(sorted(names.get(node_id, node_id) for node_id in preview.best_effort_source_ids))
            self.stdout.write(f"  ⚠ best-effort sources (freshness not guaranteed): {flagged}")
        if not wrote:
            self.stdout.write("  ⚠ none")

    def _print_verbose(self, preview: DagSchedulePreview, names: dict[str, str]) -> None:
        self.stdout.write("  Effective cadences:")
        for node_id, interval in sorted(preview.effective.items(), key=lambda item: names.get(item[0], item[0])):
            cadence = str(interval) if interval is not None else "unscheduled"
            self.stdout.write(f"    {names.get(node_id, node_id)}: {cadence}")

        self.stdout.write("  Desired tiers:")
        for interval, node_ids in sorted(preview.desired_tiers.items()):
            members = ", ".join(sorted(names.get(node_id, node_id) for node_id in node_ids))
            self.stdout.write(f"    {interval}: {members}")

        plan = preview.plan
        self.stdout.write("  Plan vs current schedules:")
        if not (plan.to_create or plan.to_update or plan.to_delete):
            self.stdout.write("    (already in sync)")
            return
        for schedule_id, (interval, node_ids) in sorted(plan.to_create.items()):
            self.stdout.write(f"    CREATE {schedule_id} ({interval}, {len(node_ids)} nodes)")
        for schedule_id, (interval, node_ids) in sorted(plan.to_update.items()):
            self.stdout.write(f"    UPDATE {schedule_id} ({interval}, {len(node_ids)} nodes)")
        for schedule_id in sorted(plan.to_delete):
            self.stdout.write(f"    DELETE {schedule_id}")

    def _print_cross_dag_duplication(self, team_id: int) -> None:
        """Which saved queries a team materializes in more than one DAG, and which are unique to
        each DAG. A query in >1 DAG is materialized redundantly; a DAG whose queries all also live
        elsewhere is safe to drop, one with unique queries is not."""
        dags = list(DAG.objects.filter(team_id=team_id))
        if len(dags) < 2:
            return
        dag_names = {dag.id: dag.name for dag in dags}
        rows = (
            Node.objects.filter(dag__in=dags)
            .exclude(type=NodeType.TABLE)
            .exclude(saved_query__deleted=True)
            .values_list("dag_id", "saved_query_id")
        )
        dags_by_query: dict[object, set[object]] = defaultdict(set)
        for dag_id, saved_query_id in rows:
            if saved_query_id is not None:
                dags_by_query[saved_query_id].add(dag_id)

        if not dags_by_query:
            return
        double_materialized = sum(1 for owning in dags_by_query.values() if len(owning) > 1)
        unique_per_dag: dict[object, int] = defaultdict(int)
        for owning in dags_by_query.values():
            if len(owning) == 1:
                unique_per_dag[next(iter(owning))] += 1

        self.stdout.write(f"\nTeam {team_id} cross-DAG duplication:")
        self.stdout.write(f"  {len(dags_by_query)} distinct saved queries across {len(dags)} DAGs")
        self.stdout.write(f"  in >1 DAG (double-materialized): {double_materialized}")
        for dag in sorted(dags, key=lambda d: dag_names[d.id]):
            unique = unique_per_dag.get(dag.id, 0)
            note = "safe to drop" if unique == 0 else "unsafe to drop"
            self.stdout.write(f"  only in {dag_names[dag.id]} ({note}): {unique}")
