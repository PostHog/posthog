import uuid
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.models.team import Team

from products.data_modeling.backend.logic.node_frequency import schedulable_nodes
from products.data_modeling.backend.logic.schedule_reconcile import (
    convert_dag_to_tiers,
    delete_v1_saved_query_schedules,
    null_saved_query_intervals,
    tiered_schedules_enabled,
)
from products.data_modeling.backend.models.dag import DAG

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Convert a team's DAGs to per-cadence-tier schedules: persist a freshness target on every "
        "schedulable node lacking one (seeded from its current cadence, never overwriting), then "
        "reconcile Temporal so one execute-dag schedule exists per tier — sweeping the legacy "
        "single per-DAG schedule and any v1 per-query schedules, so it is safe on a v1 team "
        "directly. Saved-query sync_frequency_intervals are nulled once targets "
        "are persisted (the node target becomes the only store of frequency intent). Caveat: "
        "re-running the conversion re-seeds a node whose target was explicitly cleared ('never') "
        "from the DAG's interval."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--dag-id", type=str, default=None, help="Limit to one DAG (default: all of the team's)")
        parser.add_argument(
            "--default-interval-seconds",
            type=int,
            default=None,
            help="Target for nodes with no seedable cadence anywhere (must be a supported bucket)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Delegate to preview_freshness_schedules --seed; writes nothing",
        )

    def handle(self, *args, **options):
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team with id {options['team_id']}")

        if options["dry_run"]:
            if options["default_interval_seconds"] is not None:
                raise CommandError(
                    "--default-interval-seconds has no effect under --dry-run: the preview does not seed "
                    "defaults, so it would report the very nodes the real run schedules as unscheduled"
                )
            preview_args = ["--team-id", str(team.pk), "--seed"]
            if options["dag_id"]:
                preview_args += ["--dag-id", options["dag_id"]]
            call_command("preview_freshness_schedules", *preview_args, stdout=self.stdout)
            return

        if not tiered_schedules_enabled(team):
            raise CommandError(
                f"Team {team.pk} is not on the tiered-schedules flag; converting it would create "
                "tiers that no mutation trigger maintains"
            )

        dags = DAG.objects.filter(team_id=team.pk)
        if options["dag_id"]:
            try:
                dags = dags.filter(id=uuid.UUID(options["dag_id"]))
            except ValueError:
                raise CommandError(f"--dag-id must be a UUID, got {options['dag_id']!r}")
        dag_list = list(dags)
        if not dag_list:
            raise CommandError("No matching DAGs")

        default = (
            timedelta(seconds=options["default_interval_seconds"])
            if options["default_interval_seconds"] is not None
            else None
        )
        # Seed every DAG before touching intervals: a query in two DAGs seeds from the shared
        # interval, so sweeping/nulling mid-loop would corrupt the other DAG's seed.
        seeded_by_dag = [(dag, convert_dag_to_tiers(dag, default=default)) for dag in dag_list]
        for dag, seeded in seeded_by_dag:
            nodes = list(schedulable_nodes(dag).select_related("saved_query"))
            sq_ids = [str(node.saved_query_id) for node in nodes if node.saved_query_id is not None]
            # Sweep any legacy v1 per-query schedules (no-op on a v2 team); null only the intervals
            # whose v1 schedule is gone, so a failed delete keeps its interval for a re-run.
            failed = delete_v1_saved_query_schedules(nodes, team_id=dag.team_id, dag_id=str(dag.id))
            swept = [sq_id for sq_id in sq_ids if sq_id not in failed]
            cleared = null_saved_query_intervals(dag, only_saved_query_ids=swept)
            self.stdout.write(
                f"DAG {dag.name} ({dag.id}): seeded {seeded} target(s), reconciled, "
                f"swept {len(swept)} v1 schedule(s), cleared {cleared} interval(s)"
            )
