import uuid
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.models.team import Team

from products.data_modeling.backend.logic.node_frequency import persist_seed_targets
from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_schedules, tiered_schedules_enabled
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Convert a team's DAGs to per-cadence-tier schedules: persist a freshness target on every "
        "schedulable node lacking one (seeded from its current cadence, never overwriting), then "
        "reconcile Temporal so one execute-dag schedule exists per tier — sweeping the legacy "
        "single per-DAG schedule. Saved-query sync_frequency_intervals are nulled once targets "
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
        dags = list(dags)
        if not dags:
            raise CommandError("No matching DAGs")

        default = (
            timedelta(seconds=options["default_interval_seconds"])
            if options["default_interval_seconds"] is not None
            else None
        )
        for dag in dags:
            seeded = persist_seed_targets(dag, default=default)
            reconcile_dag_schedules(dag)
            # Nulled only after targets are persisted and tiers reconciled — the node target is
            # now the only store of frequency intent, and a lingering interval could revive a
            # v1 schedule. The Node→saved-query FK has no reverse name, so go through Node.
            saved_query_ids = list(
                Node.objects.filter(dag=dag, saved_query__isnull=False).values_list("saved_query_id", flat=True)
            )
            cleared = DataWarehouseSavedQuery.objects.filter(
                id__in=saved_query_ids, sync_frequency_interval__isnull=False
            ).update(sync_frequency_interval=None)
            self.stdout.write(
                f"DAG {dag.name} ({dag.id}): seeded {seeded} target(s), reconciled, "
                f"cleared {cleared} saved-query interval(s)"
            )
