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

from posthog.models import Team
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import create_schedule, delete_schedule, schedule_exists
from posthog.temporal.common.search_attributes import (
    POSTHOG_DAG_ID_KEY,
    POSTHOG_ORG_ID_KEY,
    POSTHOG_SCHEDULE_TYPE_KEY,
    POSTHOG_TEAM_ID_KEY,
)
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs

from products.data_modeling.backend.models import DAG, DEFAULT_DAG_NAME, REVENUE_ANALYTICS_DAG_NAME, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.schedule import build_schedule_spec
from products.data_modeling.backend.services.saved_query_dag_sync import sync_saved_query_to_dag

logger = structlog.get_logger(__name__)

BATCH_DELAY_SECONDS = 0.5

# Tags the revenue analytics v2 schedule via the PostHogScheduleType search attribute so it can
# be found without scanning every schedule. Matches DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS.
REVENUE_ANALYTICS_SCHEDULE_TYPE = "revenue_analytics"


class Command(BaseCommand):
    help = (
        "Migrate teams from per-saved-query v1 schedules to per-DAG v2 schedules. "
        "Revenue analytics managed-viewset views are routed into a dedicated, protected "
        "'Revenue Analytics' DAG with its own schedule; everything else stays on the Default DAG."
    )

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
        team_ids = self._get_team_ids(options)
        total = len(team_ids)
        if total == 0:
            raise CommandError("No teams with scheduled saved queries found matching filters")

        logger.info(f"Found {total} team(s) to process")
        if not options["dry_run"] and not settings.TEST:
            confirm = input(f"\n\tWill migrate {total} teams to v2 schedules. Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        teams_by_id = {team.id: team for team in Team.objects.filter(id__in=team_ids)}
        migrated = 0
        skipped = 0
        failed = 0
        for i, team_id in enumerate(team_ids):
            team = teams_by_id.get(team_id)
            if team is None:
                continue
            try:
                if self._migrate_team(team, dry_run=options["dry_run"]):
                    migrated += 1
                else:
                    skipped += 1
            except Exception:
                failed += 1
                logger.exception("Failed to migrate team", team_id=team_id)
            logger.info(f"Progress: {i + 1}/{total} (migrated={migrated}, skipped={skipped}, failed={failed})")
            if not options["dry_run"]:
                time.sleep(BATCH_DELAY_SECONDS)

        if options["dry_run"]:
            logger.info(f"Dry run complete. Would migrate: {migrated}, Would skip: {skipped}")
        else:
            logger.info(f"Done! Migrated: {migrated}, Skipped: {skipped}, Failed: {failed}")

    def _get_team_ids(self, options) -> list[int]:
        team_ids_qs = (
            DataWarehouseSavedQuery.objects.filter(sync_frequency_interval__isnull=False, deleted=False)
            .values_list("team_id", flat=True)
            .distinct()
        )
        if options.get("team_ids") is not None:
            try:
                team_id_filter = [int(tid) for tid in options["team_ids"].split(",")]
            except ValueError:
                raise CommandError("team_ids must be a comma separated list of team IDs")
            team_ids_qs = team_ids_qs.filter(team_id__in=team_id_filter)
        if options.get("start_after_team_id") is not None:
            team_ids_qs = team_ids_qs.filter(team_id__gt=options["start_after_team_id"])
        return sorted(team_ids_qs)

    def _migrate_team(self, team: Team, *, dry_run: bool) -> bool:
        """Migrate a single team's schedules. Returns True if anything was migrated."""
        did_something = False
        # Non-managed models keep the existing per-DAG flow (one v2 schedule per Default DAG).
        for dag in DAG.objects.filter(team=team).exclude(name=REVENUE_ANALYTICS_DAG_NAME).select_related("team"):
            if self._migrate_dag(dag, dry_run=dry_run):
                did_something = True
        # Revenue analytics managed-viewset views get their own dedicated DAG and schedule.
        if self._migrate_revenue_analytics(team, dry_run=dry_run):
            did_something = True
        return did_something

    def _migrate_dag(self, dag: DAG, *, dry_run: bool) -> bool:
        """Migrate a single non-managed DAG to a v2 schedule. Returns True if migrated."""
        team = dag.team
        # materialized non-managed nodes whose saved queries have sync schedules
        scheduled_nodes = Node.objects.filter(
            dag=dag,
            saved_query__isnull=False,
            saved_query__sync_frequency_interval__isnull=False,
            saved_query__deleted=False,
            saved_query__managed_viewset__isnull=True,
        ).select_related("saved_query")
        if not scheduled_nodes.exists():
            return False
        # check that all scheduled saved queries share the same sync frequency
        intervals = list(scheduled_nodes.values_list("saved_query__sync_frequency_interval", flat=True).distinct())
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

        temporal = sync_connect()
        schedule_id = str(dag.id)
        if schedule_exists(temporal, schedule_id=schedule_id):
            logger.info("V2 schedule already exists, skipping creation", dag_id=str(dag.id), team_id=team.pk)
            return True

        self._create_dag_schedule(temporal, dag=dag, team=team, interval=interval)
        logger.info("Created v2 DAG schedule", dag_id=str(dag.id), team_id=team.pk, interval=str(interval))
        # update the DAG only after schedule creation succeeded
        if dag.name != DEFAULT_DAG_NAME:
            dag.name = DEFAULT_DAG_NAME
        dag.sync_frequency_interval = interval
        dag.save(update_fields=["name", "sync_frequency_interval"])
        logger.info("Renamed DAG", dag_id=str(dag.id), team_id=team.pk)

        saved_queries = [node.saved_query for node in scheduled_nodes if node.saved_query is not None]
        self._delete_v1_schedules(temporal, saved_queries, team)
        # null out sync_frequency_interval so v1 schedules are not re-created
        DataWarehouseSavedQuery.objects.filter(id__in=[sq.id for sq in saved_queries]).update(
            sync_frequency_interval=None
        )
        logger.info(
            "Cleared sync_frequency_interval on saved queries",
            dag_id=str(dag.id),
            team_id=team.pk,
            count=len(saved_queries),
        )
        return True

    def _migrate_revenue_analytics(self, team: Team, *, dry_run: bool) -> bool:
        """Route a team's managed-viewset views into a dedicated Revenue Analytics DAG + schedule.

        Returns True if migrated.
        """
        managed_sqs = list(
            DataWarehouseSavedQuery.objects.filter(
                team=team,
                managed_viewset__isnull=False,
                sync_frequency_interval__isnull=False,
                deleted=False,
            )
        )
        if not managed_sqs:
            return False
        intervals = {sq.sync_frequency_interval for sq in managed_sqs}
        if len(intervals) != 1:
            logger.warning(
                "Revenue analytics saved queries have multiple sync frequencies, skipping",
                team_id=team.pk,
                intervals=[str(i) for i in intervals],
            )
            return False
        interval = cast(timedelta, next(iter(intervals)))
        if dry_run:
            logger.info(
                "Would migrate revenue analytics to a dedicated DAG",
                team_id=team.pk,
                saved_queries=len(managed_sqs),
                interval=str(interval),
            )
            return True

        ra_dag = DAG.get_or_create_revenue_analytics(team)
        self._sync_nodes_into_dag(managed_sqs, ra_dag, team)
        # move the views out of any other DAG (e.g. the Default DAG from the 0006 node backfill)
        Node.objects.filter(saved_query__in=managed_sqs).exclude(dag=ra_dag).delete()
        logger.info(
            "Moved revenue analytics views into dedicated DAG",
            dag_id=str(ra_dag.id),
            team_id=team.pk,
            count=len(managed_sqs),
        )

        temporal = sync_connect()
        schedule_id = str(ra_dag.id)
        if schedule_exists(temporal, schedule_id=schedule_id):
            logger.info(
                "Revenue analytics v2 schedule already exists, skipping creation",
                dag_id=str(ra_dag.id),
                team_id=team.pk,
            )
        else:
            self._create_dag_schedule(
                temporal,
                dag=ra_dag,
                team=team,
                interval=interval,
                schedule_type=REVENUE_ANALYTICS_SCHEDULE_TYPE,
            )
            logger.info(
                "Created revenue analytics v2 DAG schedule",
                dag_id=str(ra_dag.id),
                team_id=team.pk,
                interval=str(interval),
            )
        if ra_dag.sync_frequency_interval != interval:
            ra_dag.sync_frequency_interval = interval
            ra_dag.save(update_fields=["sync_frequency_interval"])

        self._delete_v1_schedules(temporal, managed_sqs, team)
        DataWarehouseSavedQuery.objects.filter(id__in=[sq.id for sq in managed_sqs]).update(
            sync_frequency_interval=None
        )
        logger.info(
            "Cleared sync_frequency_interval on revenue analytics saved queries",
            team_id=team.pk,
            count=len(managed_sqs),
        )
        return True

    def _sync_nodes_into_dag(self, saved_queries: list[DataWarehouseSavedQuery], dag: DAG, team: Team) -> None:
        """Ensure each saved query has a Node in `dag`, syncing in dependency order.

        `resolve_dependency_to_node` only finds existing view nodes in the target DAG, so views
        that depend on each other must be synced parents-first. We retry in passes until a pass
        makes no progress, then log whatever could not be resolved.
        """
        remaining = list(saved_queries)
        while remaining:
            progressed: list[DataWarehouseSavedQuery] = []
            still: list[DataWarehouseSavedQuery] = []
            for sq in remaining:
                try:
                    sync_saved_query_to_dag(sq, dag=dag)
                    progressed.append(sq)
                except Exception:
                    still.append(sq)
            if not progressed:
                for sq in still:
                    logger.warning(
                        "Could not sync saved query into DAG (unresolved dependencies)",
                        saved_query_id=str(sq.id),
                        team_id=team.pk,
                    )
                return
            remaining = still

    def _create_dag_schedule(
        self,
        temporal,
        *,
        dag: DAG,
        team: Team,
        interval: timedelta,
        schedule_type: str | None = None,
    ) -> None:
        inputs = ExecuteDAGInputs(team_id=team.pk, dag_id=str(dag.id), node_ids=None, duckgres_only=False)
        spec = build_schedule_spec(entity_id=dag.id, interval=interval, team_timezone=team.timezone)
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
        search_attributes = [
            SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team.pk),
            SearchAttributePair(key=POSTHOG_ORG_ID_KEY, value=str(team.organization_id)),
            SearchAttributePair(key=POSTHOG_DAG_ID_KEY, value=str(dag.id)),
        ]
        if schedule_type is not None:
            search_attributes.append(SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=schedule_type))
        create_schedule(
            temporal,
            id=str(dag.id),
            schedule=schedule,
            trigger_immediately=False,
            search_attributes=TypedSearchAttributes(search_attributes=search_attributes),
        )

    def _delete_v1_schedules(self, temporal, saved_queries: list[DataWarehouseSavedQuery], team: Team) -> None:
        """Delete the old per-saved-query v1 (data-modeling-run) schedules."""
        deleted_count = 0
        failed_schedule_ids: list[str] = []
        for saved_query in saved_queries:
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
                team_id=team.pk,
                failed_schedule_ids=failed_schedule_ids,
            )
        logger.info(
            "Deleted old v1 schedules",
            team_id=team.pk,
            deleted=deleted_count,
            total=len(saved_queries),
        )
