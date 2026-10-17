from collections.abc import Iterable
from datetime import timedelta
from itertools import groupby

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import Exists, OuterRef

from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.data_modeling.backend.logic.node_frequency import persist_seed_targets
from products.data_modeling.backend.logic.saved_query_dag_sync import (
    adopt_saved_query_without_edges,
    lineage_database,
    sync_saved_query_to_dag,
)
from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_schedules
from products.data_modeling.backend.logic.tier_run_report import MATERIALIZING_TYPES
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.modeling import UnknownParentError
from products.data_modeling.backend.models.node import Node

DEFAULT_MATERIALIZED_TARGET = timedelta(days=1)
ADOPTABLE_SYNC_ERRORS = (BaseHogQLError, UnknownParentError, ObjectDoesNotExist)


@frozen
class TeamBackfill:
    synced: int
    adopted: int
    seeded: int
    failed: dict[str, str]


class Command(BaseCommand):
    help = (
        "Give every live saved query that has no DAG node a node in its team's default DAG. "
        "A query whose lineage does not resolve gets a node with no edges and a sync-failed marker. "
        "A materialized query gets a freshness target, its own interval or else its DAG's or else 1 day, "
        "so a tier schedule picks it up. Any other sync error is reported and left for a re-run. "
        "Each team's DAG schedules are reconciled afterwards, and always for a team passed with --team-id. "
        "Managed-viewset queries are skipped. Dry run unless --apply is passed."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", dest="team_ids", help="Limit to this team.")
        parser.add_argument("--apply", action="store_true", help="Write the nodes. Without it, only list them.")

    def handle(self, *args: object, team_ids: list[int] | None, apply: bool, **options: object) -> None:
        nodeless = nodeless_saved_queries(team_ids)
        teams = sorted({saved_query.team_id for saved_query in nodeless})
        self.stdout.write(f"{len(nodeless)} nodeless saved queries across {len(teams)} teams")
        if not apply:
            for saved_query in nodeless:
                self.stdout.write(f"  team {saved_query.team_id}: {saved_query.name} ({saved_query.id})")
            return

        dags_to_reconcile = {
            team.pk: DAG.get_or_create_default(team) for team in Team.objects.filter(id__in=team_ids or [])
        }
        for team_id, grouped in groupby(nodeless, key=lambda saved_query: saved_query.team_id):
            team_queries = list(grouped)
            dag = DAG.get_or_create_default(team_queries[0].team)
            self._report(team_id, backfill_team(team_queries, dag))
            dags_to_reconcile[team_id] = dag
        for team_id, dag in dags_to_reconcile.items():
            self._reconcile(team_id, dag)

    def _report(self, team_id: int, result: TeamBackfill) -> None:
        for name, error in result.failed.items():
            self.stderr.write(f"  team {team_id}: FAILED {name}, re-run to retry: {error}")
        self.stdout.write(
            f"  team {team_id}: synced {result.synced}, adopted without edges {result.adopted}, "
            f"failed {len(result.failed)}, seeded targets {result.seeded}"
        )

    def _reconcile(self, team_id: int, dag: DAG) -> None:
        try:
            applied = reconcile_dag_schedules(dag, require_tiered=True)
        except Exception as error:
            self.stderr.write(
                f"  team {team_id}: schedule reconcile FAILED, re-run with --team-id {team_id} --apply: {error!r}"
            )
            return
        if not applied:
            self.stderr.write(f"  team {team_id}: schedules not reconciled, the DAG still runs on a pre-tier schedule")


def nodeless_saved_queries(team_ids: list[int] | None) -> list[DataWarehouseSavedQuery]:
    queryset = (
        DataWarehouseSavedQuery.objects.exclude(deleted=True)
        .filter(managed_viewset__isnull=True)
        .exclude(Exists(Node.objects.filter(saved_query_id=OuterRef("pk"))))
        .select_related("team")
        .order_by("team_id", "created_at")
    )
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)
    return list(queryset)


def backfill_team(saved_queries: list[DataWarehouseSavedQuery], dag: DAG) -> TeamBackfill:
    database = lineage_database(dag.team)
    with transaction.atomic():
        synced, unresolved = sync_until_stuck(saved_queries, dag, database)
        adoptable = {
            saved_query: error for saved_query, error in unresolved.items() if isinstance(error, ADOPTABLE_SYNC_ERRORS)
        }
        for saved_query, error in adoptable.items():
            adopt_saved_query_without_edges(saved_query.team_id, saved_query.id, str(error), dag_id=dag.id)
        # A child that only failed because its parent had no node can sync now that the parent has one.
        resynced, _ = sync_until_stuck(list(adoptable), dag, database)
        synced.extend(resynced)
        adoptable = {saved_query: error for saved_query, error in adoptable.items() if saved_query not in resynced}
        materializing_node_ids = Node.objects.filter(
            dag=dag, saved_query__in=[*synced, *adoptable], type__in=MATERIALIZING_TYPES
        ).values_list("id", flat=True)
        seeded = persist_seed_targets(
            dag,
            default=DEFAULT_MATERIALIZED_TARGET,
            only_node_ids={str(node_id) for node_id in materializing_node_ids},
        )
    return TeamBackfill(
        synced=len(synced),
        adopted=len(adoptable),
        seeded=seeded,
        failed={
            saved_query.name: repr(error) for saved_query, error in unresolved.items() if saved_query not in adoptable
        },
    )


def sync_until_stuck(
    saved_queries: Iterable[DataWarehouseSavedQuery], dag: DAG, database: Database
) -> tuple[list[DataWarehouseSavedQuery], dict[DataWarehouseSavedQuery, Exception]]:
    pending = list(saved_queries)
    synced: list[DataWarehouseSavedQuery] = []
    while True:
        failures: dict[DataWarehouseSavedQuery, Exception] = {}
        for saved_query in pending:
            try:
                with transaction.atomic():
                    sync_saved_query_to_dag(saved_query, dag=dag, reconcile=False, database=database)
            except Exception as error:
                failures[saved_query] = error
                continue
            synced.append(saved_query)
        if not failures or len(failures) == len(pending):
            return synced, failures
        pending = list(failures)
