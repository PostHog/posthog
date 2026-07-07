import uuid

from django.core.management.base import BaseCommand, CommandError

from products.data_modeling.backend.logic.schedule_reconcile import DagSchedulePreview, preview_dag_schedules
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node


class Command(BaseCommand):
    help = (
        "Dry-run: show the per-cadence-tier schedules a DAG would get from its nodes' freshness "
        "targets, and the create/update/delete plan against its current schedules. Reads only — "
        "never creates, updates, or deletes a schedule, and touches no live read/write path."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--dag-id", type=str, default=None, help="Limit to one DAG (default: all of the team's)")
        parser.add_argument(
            "--seed",
            action="store_true",
            help="Model the go-live plan: seed a target from current cadence for nodes without one (in memory, no write)",
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
            self._preview(dag, seed=options["seed"])
        self.stdout.write("\n(dry run — no schedules were created, updated, or deleted)")

    def _preview(self, dag: DAG, *, seed: bool) -> None:
        preview = preview_dag_schedules(dag, seed=seed)
        names = {str(node_id): name for node_id, name in Node.objects.filter(dag=dag).values_list("id", "name")}

        seeded_note = "  [targets seeded from current cadence]" if preview.seeded else ""
        self.stdout.write(f"\nDAG {dag.name} ({dag.id}) — team {dag.team_id}{seeded_note}")

        self.stdout.write("  Effective cadences:")
        for node_id, interval in sorted(preview.effective.items(), key=lambda item: names.get(item[0], item[0])):
            cadence = str(interval) if interval is not None else "unscheduled"
            self.stdout.write(f"    {names.get(node_id, node_id)}: {cadence}")

        self.stdout.write("  Desired tiers:")
        for interval, node_ids in sorted(preview.desired_tiers.items()):
            members = ", ".join(sorted(names.get(node_id, node_id) for node_id in node_ids))
            self.stdout.write(f"    {interval}: {members}")

        self._print_plan(preview)

        for tier in sorted(preview.unsatisfiable, key=lambda t: names.get(t.node_id, t.node_id)):
            self.stdout.write(
                f"  ⚠ unsatisfiable: {names.get(tier.node_id, tier.node_id)} would run every {tier.effective} "
                f"but its sources only deliver every {tier.floor}"
            )

        for interval in preview.unsupported_tiers:
            self.stdout.write(f"  ⚠ unsupported tier: {interval} is not a schedulable bucket — reconcile would refuse")

        for invalid in sorted(preview.invalid_targets, key=lambda t: names.get(t.node_id, t.node_id)):
            ceiling = str(invalid.ceiling) if invalid.ceiling is not None else "none"
            self.stdout.write(
                f"  ⚠ invalid declared target: {names.get(invalid.node_id, invalid.node_id)} declares "
                f"{invalid.target} but its legal range is [{invalid.floor} … {ceiling}]"
            )

        if preview.best_effort_source_ids:
            flagged = ", ".join(sorted(names.get(node_id, node_id) for node_id in preview.best_effort_source_ids))
            self.stdout.write(f"  ⚠ best-effort sources (freshness not guaranteed): {flagged}")

    def _print_plan(self, preview: DagSchedulePreview) -> None:
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
