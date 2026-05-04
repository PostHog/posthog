import time
from dataclasses import asdict
from datetime import timedelta
from typing import cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog
import temporalio
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleState,
)
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import create_schedule, delete_schedule, schedule_exists
from posthog.temporal.common.search_attributes import POSTHOG_DAG_ID_KEY, POSTHOG_ORG_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs

from products.data_modeling.backend.models import DAG, Node
from products.data_modeling.backend.schedule import build_schedule_spec
from products.data_warehouse.backend.models import DataWarehouseSavedQuery

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
        for i, dag in enumerate(dags.iterator()):
            try:
                result = self._migrate_dag(dag, dry_run=options["dry_run"])
                if result:
                    migrated += 1
                else:
                    skipped += 1
            except Exception:
                failed += 1
                logger.exception("Failed to migrate DAG", dag_id=str(dag.id), team_id=dag.team_id)
            logger.info(f"Progress: {i + 1}/{total} (migrated={migrated}, skipped={skipped}, failed={failed})")
            if not options["dry_run"]:
                time.sleep(BATCH_DELAY_SECONDS)
        if options["dry_run"]:
            logger.info(f"Dry run complete. Would migrate: {migrated}, Would skip: {skipped}")
        else:
            logger.info(f"Done! Migrated: {migrated}, Skipped: {skipped}, Failed: {failed}")

    def _migrate_dag(self, dag: DAG, *, dry_run: bool) -> bool:
        """Migrate a single DAG to a v2 schedule.

        Returns True if migrated, False if skipped.
        """
        team = dag.team
        # find all materialized nodes in this DAG that have saved queries with sync schedules
        scheduled_nodes = Node.objects.filter(
            dag=dag,
            saved_query__isnull=False,
            saved_query__sync_frequency_interval__isnull=False,
            saved_query__deleted=False,
        ).select_related("saved_query")
        if not scheduled_nodes.exists():
            logger.info("No scheduled nodes found, skipping", dag_id=str(dag.id), team_id=team.pk)
            return False
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
            return False
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
            return True
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
            search_attributes = TypedSearchAttributes(
                search_attributes=[
                    SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team.pk),
                    SearchAttributePair(key=POSTHOG_ORG_ID_KEY, value=str(team.organization_id)),
                    SearchAttributePair(key=POSTHOG_DAG_ID_KEY, value=str(dag.id)),
                ]
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
            # delete old per-node schedules
            deleted_count = 0
            failed_schedule_ids: list[str] = []
            for node in scheduled_nodes:
                saved_query = node.saved_query
                if saved_query is None:
                    continue
                try:
                    delete_schedule(temporal, schedule_id=str(saved_query.id))
                    deleted_count += 1
                except temporalio.service.RPCError as e:
                    if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                        logger.warning(
                            "Old schedule not found (already deleted?)",
                            saved_query_id=str(saved_query.id),
                            team_id=team.pk,
                        )
                    else:
                        failed_schedule_ids.append(str(saved_query.id))
                        logger.exception(
                            "Failed to delete old schedule",
                            saved_query_id=str(saved_query.id),
                            team_id=team.pk,
                        )
            if failed_schedule_ids:
                logger.warning(
                    "Some old schedules could not be deleted",
                    dag_id=str(dag.id),
                    team_id=team.pk,
                    failed_schedule_ids=failed_schedule_ids,
                )
            logger.info(
                "Deleted old per-node schedules",
                dag_id=str(dag.id),
                team_id=team.pk,
                deleted=deleted_count,
                total=scheduled_nodes.count(),
            )
            # null out sync_frequency_interval on migrated saved queries so v1 schedules are not re-created
            migrated_sq_ids = [node.saved_query_id for node in scheduled_nodes if node.saved_query_id is not None]
            DataWarehouseSavedQuery.objects.filter(id__in=migrated_sq_ids).update(sync_frequency_interval=None)
            logger.info(
                "Cleared sync_frequency_interval on saved queries",
                dag_id=str(dag.id),
                team_id=team.pk,
                count=len(migrated_sq_ids),
            )
        return True
