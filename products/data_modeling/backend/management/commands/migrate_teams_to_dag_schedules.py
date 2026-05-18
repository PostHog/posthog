import time
from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta

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

from posthog.hogql.database.database import Database

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import create_schedule, delete_schedule, schedule_exists
from posthog.temporal.common.search_attributes import POSTHOG_DAG_ID_KEY, POSTHOG_ORG_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs

from products.data_modeling.backend.models import DAG, Edge, Node
from products.data_modeling.backend.schedule import build_schedule_spec
from products.data_modeling.backend.services.saved_query_dag_sync import resolve_dependency_to_node
from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.modeling import UnknownParentError, get_parents_from_model_query

logger = structlog.get_logger(__name__)

BATCH_DELAY_SECONDS = 0.5


class Command(BaseCommand):
    help = "Migrate teams from per-node v1 schedules to per-frequency v2 DAG schedules"

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
        """Migrate a single DAG to one or more v2 cohort schedules.

        Each distinct sync_frequency_interval across the source DAG's scheduled
        nodes becomes its own cohort DAG (e.g., 'Default (1h)', 'Default (6h)')
        with its own Temporal schedule. Cross-cohort edges are dropped — the
        underlying HogQL dependency still resolves at query time, but the v2
        orchestrator stops enforcing freshness between cohorts.

        Returns True if migrated, False if skipped.
        """
        team = dag.team
        scheduled_nodes = list(
            Node.objects.filter(
                dag=dag,
                saved_query__isnull=False,
                saved_query__sync_frequency_interval__isnull=False,
                saved_query__deleted=False,
            ).select_related("saved_query")
        )
        if not scheduled_nodes:
            logger.info("No scheduled nodes found, skipping", dag_id=str(dag.id), team_id=team.pk)
            return False

        nodes_by_interval: dict[timedelta, list[Node]] = defaultdict(list)
        for node in scheduled_nodes:
            assert node.saved_query is not None  # filter above guarantees this
            nodes_by_interval[node.saved_query.sync_frequency_interval].append(node)

        if dry_run:
            logger.info(
                "Would migrate DAG",
                dag_id=str(dag.id),
                dag_name=dag.name,
                team_id=team.pk,
                cohorts={str(i): len(ns) for i, ns in nodes_by_interval.items()},
            )
            return True

        temporal = sync_connect()
        for interval, cohort_nodes in nodes_by_interval.items():
            self._migrate_cohort(temporal, team, interval, cohort_nodes)

        self._delete_v1_schedules(temporal, team, scheduled_nodes)
        self._clear_saved_query_intervals(scheduled_nodes)
        return True

    def _migrate_cohort(
        self,
        temporal,
        team,
        interval: timedelta,
        cohort_nodes: list[Node],
    ) -> None:
        """Move a frequency cohort into its own DAG and ensure its v2 schedule exists."""
        cohort_dag = DAG.get_or_create_for_frequency(team, interval)
        schedule_id = str(cohort_dag.id)

        node_ids = [n.id for n in cohort_nodes]
        Node.objects.filter(id__in=node_ids).exclude(dag=cohort_dag).update(dag=cohort_dag)
        # refresh in-memory dag_id so callers downstream don't see stale FKs
        for node in cohort_nodes:
            node.dag = cohort_dag
            node.dag_id = cohort_dag.id

        self._rebuild_cohort_edges(team, cohort_nodes, cohort_dag)

        if schedule_exists(temporal, schedule_id=schedule_id):
            logger.info(
                "Cohort v2 schedule already exists, skipping creation",
                dag_id=str(cohort_dag.id),
                team_id=team.pk,
                interval=str(interval),
            )
            return

        self._create_cohort_schedule(temporal, team, cohort_dag, interval)

    def _rebuild_cohort_edges(self, team, cohort_nodes: list[Node], cohort_dag: DAG) -> None:
        """Rebuild incoming edges for each cohort node inside the cohort DAG.

        Cross-cohort dependencies (a node in this cohort that depended on a node
        now living in a different cohort DAG) are dropped — `resolve_dependency_to_node`
        raises Node.DoesNotExist when the source's dag != cohort_dag, and we
        log+skip rather than fail the migration.
        """
        database = Database.create_for(team=team)
        for node in cohort_nodes:
            Edge.objects.filter(team=team, target=node).delete()
            saved_query = node.saved_query
            if saved_query is None:
                continue
            query_text = saved_query.query.get("query") if saved_query.query else None
            if not query_text:
                continue
            try:
                deps = get_parents_from_model_query(team, saved_query.name, query_text)
            except Exception:
                logger.exception(
                    "Failed to parse saved query during cohort migration",
                    saved_query_id=str(saved_query.id),
                    team_id=team.pk,
                )
                continue
            for dep_name in deps:
                self._create_cohort_edge(team, cohort_dag, node, dep_name, database)

    def _create_cohort_edge(self, team, cohort_dag: DAG, target: Node, dep_name: str, database: Database) -> None:
        try:
            source = resolve_dependency_to_node(dep_name, team, database, cohort_dag)
        except (Node.DoesNotExist, DataWarehouseSavedQuery.DoesNotExist, UnknownParentError):
            logger.info(
                "Dropping cross-cohort dependency",
                team_id=team.pk,
                cohort_dag_id=str(cohort_dag.id),
                target_node_id=str(target.id),
                dependency_name=dep_name,
            )
            return
        try:
            Edge.objects.create(team=team, dag=cohort_dag, source=source, target=target)
        except Exception:
            logger.exception(
                "Failed to create cohort edge",
                team_id=team.pk,
                cohort_dag_id=str(cohort_dag.id),
                source_node_id=str(source.id),
                target_node_id=str(target.id),
            )

    def _create_cohort_schedule(self, temporal, team, cohort_dag: DAG, interval: timedelta) -> None:
        inputs = ExecuteDAGInputs(
            team_id=team.pk,
            dag_id=str(cohort_dag.id),
            node_ids=None,
            duckgres_only=False,
        )
        spec = build_schedule_spec(
            entity_id=cohort_dag.id,
            interval=interval,
            team_timezone=team.timezone,
        )
        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "data-modeling-execute-dag",
                asdict(inputs),
                id=f"execute-dag-{cohort_dag.id}",
                task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=60),
                    maximum_attempts=3,
                    non_retryable_error_types=["NondeterminismError", "CancelledError"],
                ),
            ),
            spec=spec,
            state=ScheduleState(note=f"DAG schedule for team {team.pk} cohort {interval}"),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        )
        search_attributes = TypedSearchAttributes(
            search_attributes=[
                SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team.pk),
                SearchAttributePair(key=POSTHOG_ORG_ID_KEY, value=str(team.organization_id)),
                SearchAttributePair(key=POSTHOG_DAG_ID_KEY, value=str(cohort_dag.id)),
            ]
        )
        create_schedule(
            temporal,
            id=str(cohort_dag.id),
            schedule=schedule,
            trigger_immediately=False,
            search_attributes=search_attributes,
        )
        # ensure the DAG's stored frequency matches the schedule's frequency
        if cohort_dag.sync_frequency_interval != interval:
            cohort_dag.sync_frequency_interval = interval
            cohort_dag.save(update_fields=["sync_frequency_interval"])
        logger.info(
            "Created v2 cohort schedule",
            dag_id=str(cohort_dag.id),
            team_id=team.pk,
            interval=str(interval),
        )

    def _delete_v1_schedules(self, temporal, team, scheduled_nodes: list[Node]) -> None:
        deleted = 0
        failed: list[str] = []
        for node in scheduled_nodes:
            saved_query = node.saved_query
            if saved_query is None:
                continue
            try:
                delete_schedule(temporal, schedule_id=str(saved_query.id))
                deleted += 1
            except temporalio.service.RPCError as e:
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    logger.warning(
                        "Old schedule not found (already deleted?)",
                        saved_query_id=str(saved_query.id),
                        team_id=team.pk,
                    )
                else:
                    failed.append(str(saved_query.id))
                    logger.exception(
                        "Failed to delete old schedule",
                        saved_query_id=str(saved_query.id),
                        team_id=team.pk,
                    )
        if failed:
            logger.warning(
                "Some old schedules could not be deleted",
                team_id=team.pk,
                failed_schedule_ids=failed,
            )
        logger.info(
            "Deleted old per-node schedules",
            team_id=team.pk,
            deleted=deleted,
            total=len(scheduled_nodes),
        )

    def _clear_saved_query_intervals(self, scheduled_nodes: list[Node]) -> None:
        sq_ids = [n.saved_query_id for n in scheduled_nodes if n.saved_query_id is not None]
        if not sq_ids:
            return
        DataWarehouseSavedQuery.objects.filter(id__in=sq_ids).update(sync_frequency_interval=None)
        logger.info("Cleared sync_frequency_interval on saved queries", count=len(sq_ids))
