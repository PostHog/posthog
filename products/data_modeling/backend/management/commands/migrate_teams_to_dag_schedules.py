import time
from dataclasses import asdict
from datetime import timedelta
from itertools import groupby
from typing import cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

import structlog
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleState,
)
from temporalio.common import RetryPolicy

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import create_schedule, schedule_exists
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs

from products.data_modeling.backend.logic.schedule_reconcile import (
    convert_dag_to_tiers,
    delete_v1_saved_query_schedules,
    null_saved_query_intervals,
    tiered_schedules_enabled,
)
from products.data_modeling.backend.models import DAG, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.schedule import build_schedule_spec, dag_schedule_search_attributes

logger = structlog.get_logger(__name__)

BATCH_DELAY_SECONDS = 0.5


class Command(BaseCommand):
    help = "Migrate teams from per-node v1 schedules to a single per-DAG v2 schedule"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            default=None,
            type=str,
            help="Comma separated list of team IDs to migrate",
        )
        parser.add_argument(
            "--start-after-team-id",
            default=None,
            type=int,
            help="Resume after this team ID (exclusive), following the team_id ordering used by this command",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only show what would be done without making changes",
        )

    def handle(self, **options):
        dags = DAG.objects.select_related("team")
        if options.get("team_ids") is not None:
            try:
                team_ids = [int(tid) for tid in options["team_ids"].split(",")]
            except ValueError:
                raise CommandError("team_ids must be a comma separated list of team IDs")
            dags = dags.filter(team_id__in=team_ids)
        if options.get("start_after_team_id") is not None:
            dags = dags.filter(team_id__gt=options["start_after_team_id"])
        dags = dags.order_by("team_id")
        total = dags.count()
        if total == 0:
            raise CommandError("No DAGs found matching filters")
        logger.info(f"Found {total} DAG(s) to process")
        if not options["dry_run"] and not settings.TEST:
            confirm = input(f"\n\tWill migrate {total} DAGs to v2 schedules. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return
        migrated = 0
        skipped = 0
        failed = 0
        processed = 0
        dry_run = options["dry_run"]
        # Group DAGs by team so a saved query shared across two of a team's DAGs is seeded from
        # every DAG before any interval is nulled (see _migrate_team_tiered). DAGs are ordered by
        # team_id, which groupby requires to keep each team's rows contiguous.
        for _team_id, group in groupby(dags.iterator(), key=lambda dag: dag.team_id):
            team_dags = list(group)
            if tiered_schedules_enabled(team_dags[0].team):
                outcomes = self._migrate_team_tiered(team_dags, dry_run=dry_run)
            else:
                outcomes = [self._migrate_dag_legacy(dag, dry_run=dry_run) for dag in team_dags]
            for outcome in outcomes:
                if outcome == "migrated":
                    migrated += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    failed += 1
                processed += 1
                logger.info(f"Progress: {processed}/{total} (migrated={migrated}, skipped={skipped}, failed={failed})")
                if not dry_run:
                    time.sleep(BATCH_DELAY_SECONDS)
        if dry_run:
            logger.info(f"Dry run complete. Would migrate: {migrated}, Would skip: {skipped}")
        else:
            logger.info(f"Done! Migrated: {migrated}, Skipped: {skipped}, Failed: {failed}")

    def _scheduled_nodes(self, dag: DAG) -> QuerySet[Node]:
        """Materialized nodes in this DAG whose saved query still carries a v1 sync interval."""
        return Node.objects.filter(
            dag=dag,
            saved_query__isnull=False,
            saved_query__sync_frequency_interval__isnull=False,
            saved_query__deleted=False,
        ).select_related("saved_query")

    def _migrate_team_tiered(self, team_dags: list[DAG], *, dry_run: bool) -> list[str]:
        """Migrate all of a team's v1 DAGs straight to per-cadence-tier v2 schedules.

        Two-phase so it stays correct when a saved query has schedulable nodes in two of the team's
        DAGs: phase 1 seeds every DAG's node targets (never overwriting) while the shared
        sync_frequency_interval is still intact; phase 2 sweeps the v1 schedules and nulls the
        consumed intervals. Nulling per DAG mid-seed would leave the second DAG to re-seed from the
        1-day DAG default — a silent freshness regression. Mirrors reconcile_freshness_schedules.

        Idempotent by construction: seeding never overwrites an existing target, the reconcile
        converges whatever schedules exist, and the v1 deletes tolerate NOT_FOUND.

        Returns one outcome ("migrated"/"skipped"/"failed") per DAG, in team_dags order.
        """
        outcomes: list[str] = []
        seeded: list[tuple[DAG, list[Node]]] = []
        # Phase 1 — seed every DAG before any interval is nulled.
        for dag in team_dags:
            try:
                nodes = list(self._scheduled_nodes(dag))
                if not nodes:
                    logger.info("No scheduled nodes found, skipping", dag_id=str(dag.id), team_id=dag.team_id)
                    outcomes.append("skipped")
                    continue
                intervals = sorted(
                    {str(node.saved_query.sync_frequency_interval) for node in nodes if node.saved_query is not None}
                )
                if dry_run:
                    logger.info(
                        "Would migrate DAG to cadence tiers",
                        dag_id=str(dag.id),
                        dag_name=dag.name,
                        team_id=dag.team_id,
                        intervals=intervals,
                        scheduled_nodes=len(nodes),
                    )
                    outcomes.append("migrated")
                    continue
                seeded_targets = convert_dag_to_tiers(dag)
                logger.info(
                    "Migrated DAG to cadence tiers",
                    dag_id=str(dag.id),
                    team_id=dag.team_id,
                    seeded_targets=seeded_targets,
                    intervals=intervals,
                )
                seeded.append((dag, nodes))
                outcomes.append("migrated")
            except Exception:
                logger.exception("Failed to migrate DAG", dag_id=str(dag.id), team_id=dag.team_id)
                outcomes.append("failed")
        if dry_run or not seeded:
            return outcomes
        # Phase 2 — every DAG is now seeded, so sweeping v1 schedules and nulling the consumed
        # intervals can no longer strand another DAG's seed. Isolate the connect so a Temporal
        # outage skips this team's sweep (idempotent, retried on re-run) instead of aborting the
        # whole fleet run and leaving every later team unprocessed.
        try:
            temporal = sync_connect()
        except Exception:
            logger.exception(
                "Failed to connect to Temporal for v1 sweep; leaving it for a re-run",
                team_id=team_dags[0].team_id,
            )
            return outcomes
        for dag, nodes in seeded:
            try:
                failed_schedule_ids = delete_v1_saved_query_schedules(
                    nodes, team_id=dag.team_id, dag_id=str(dag.id), temporal=temporal
                )
                # Null intervals only for queries whose v1 schedule actually went away: a failed
                # delete keeps its interval so a re-run retries it.
                deleted_sq_ids = [
                    str(node.saved_query_id)
                    for node in nodes
                    if node.saved_query_id is not None and str(node.saved_query_id) not in failed_schedule_ids
                ]
                cleared = null_saved_query_intervals(dag, only_saved_query_ids=deleted_sq_ids)
                logger.info(
                    "Cleared sync_frequency_interval on saved queries",
                    dag_id=str(dag.id),
                    team_id=dag.team_id,
                    count=cleared,
                )
            except Exception:
                logger.exception(
                    "Failed to sweep v1 schedules after tier conversion",
                    dag_id=str(dag.id),
                    team_id=dag.team_id,
                )
        return outcomes

    def _migrate_dag_legacy(self, dag: DAG, *, dry_run: bool) -> str:
        """Migrate one DAG to a single per-DAG v2 schedule (pre-tiers path, flag off).

        Returns "migrated", "skipped", or "failed".
        """
        try:
            return self._do_migrate_dag_legacy(dag, dry_run=dry_run)
        except Exception:
            logger.exception("Failed to migrate DAG", dag_id=str(dag.id), team_id=dag.team_id)
            return "failed"

    def _do_migrate_dag_legacy(self, dag: DAG, *, dry_run: bool) -> str:
        team = dag.team
        scheduled_nodes = self._scheduled_nodes(dag)
        if not scheduled_nodes.exists():
            logger.info("No scheduled nodes found, skipping", dag_id=str(dag.id), team_id=team.pk)
            return "skipped"
        # check that all scheduled saved queries share the same sync frequency
        distinct_intervals = scheduled_nodes.values_list("saved_query__sync_frequency_interval", flat=True).distinct()
        intervals = list(distinct_intervals)
        if len(intervals) != 1:
            logger.warning(
                "DAG has multiple sync frequencies, skipping",
                dag_id=str(dag.id),
                team_id=team.pk,
                intervals=[str(i) for i in intervals],
            )
            return "skipped"
        interval = cast(timedelta, intervals[0])
        if dry_run:
            logger.info(
                "Would migrate DAG",
                dag_id=str(dag.id),
                dag_name=dag.name,
                team_id=team.pk,
                interval=str(interval),
                scheduled_nodes=scheduled_nodes.count(),
            )
            return "migrated"
        # create the v2 DAG schedule
        temporal = sync_connect()
        schedule_id = str(dag.id)
        if schedule_exists(temporal, schedule_id=schedule_id):
            logger.info("V2 schedule already exists, skipping creation", dag_id=str(dag.id), team_id=team.pk)
        else:
            inputs = ExecuteDAGInputs(
                team_id=team.pk,
                dag_id=str(dag.id),
                node_ids=None,
                duckgres_only=False,
            )
            spec = build_schedule_spec(
                entity_id=dag.id,
                interval=interval,
                team_timezone=team.timezone,
            )
            schedule = Schedule(
                action=ScheduleActionStartWorkflow(
                    "data-modeling-execute-dag",
                    asdict(inputs),
                    id=f"execute-dag-{dag.id}",
                    task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=10),
                        maximum_interval=timedelta(seconds=60),
                        maximum_attempts=3,
                        non_retryable_error_types=["NondeterminismError", "CancelledError"],
                    ),
                ),
                spec=spec,
                state=ScheduleState(note=f"DAG schedule for team {team.pk}"),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            )
            search_attributes = dag_schedule_search_attributes(
                team_id=team.pk,
                organization_id=str(team.organization_id),
                dag_id=str(dag.id),
            )
            create_schedule(
                temporal,
                id=schedule_id,
                schedule=schedule,
                trigger_immediately=False,
                search_attributes=search_attributes,
            )
            logger.info("Created v2 DAG schedule", dag_id=str(dag.id), team_id=team.pk, interval=str(interval))
            # update the DAG only after schedule creation succeeded
            dag.name = "Default"
            dag.sync_frequency_interval = interval
            dag.save(update_fields=["name", "sync_frequency_interval"])
            logger.info("Renamed DAG", dag_id=str(dag.id), team_id=team.pk)
            delete_v1_saved_query_schedules(scheduled_nodes, team_id=team.pk, dag_id=str(dag.id), temporal=temporal)
            # null out sync_frequency_interval on migrated saved queries so v1 schedules are not re-created
            migrated_sq_ids = [node.saved_query_id for node in scheduled_nodes if node.saved_query_id is not None]
            DataWarehouseSavedQuery.objects.filter(id__in=migrated_sq_ids).update(sync_frequency_interval=None)
            logger.info(
                "Cleared sync_frequency_interval on saved queries",
                dag_id=str(dag.id),
                team_id=team.pk,
                count=len(migrated_sq_ids),
            )
        return "migrated"
