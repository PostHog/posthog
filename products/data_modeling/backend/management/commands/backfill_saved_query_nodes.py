from collections.abc import Iterable
from datetime import timedelta
from itertools import groupby

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Exists, OuterRef

from posthog.hogql.errors import BaseHogQLError

from products.data_modeling.backend.logic.node_frequency import get_declared_target, set_declared_target
from products.data_modeling.backend.logic.saved_query_dag_sync import (
    adopt_saved_query_without_edges,
    sync_saved_query_to_dag,
)
from products.data_modeling.backend.logic.schedule_reconcile import maybe_reconcile_dag
from products.data_modeling.backend.logic.tier_run_report import MATERIALIZING_TYPES
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.modeling import UnknownParentError
from products.data_modeling.backend.models.node import Node

DEFAULT_MATERIALIZED_TARGET = timedelta(days=1)
ADOPTABLE_SYNC_ERRORS = (BaseHogQLError, UnknownParentError, ObjectDoesNotExist)


class Command(BaseCommand):
    help = (
        "Give every live saved query that has no DAG node a node in its team's default DAG. "
        "A query whose lineage does not resolve gets a node with no edges and a sync-failed marker. "
        "A materialized query gets a freshness target, its own interval or else its DAG's or else 1 day, "
        "so a tier schedule picks it up. Any other sync error is reported and left for a re-run. "
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

        synced = adopted = seeded = failed = 0
        for team_id, grouped in groupby(nodeless, key=lambda saved_query: saved_query.team_id):
            team_queries = list(grouped)
            dag = DAG.get_or_create_default(team_queries[0].team)
            nodes, unresolved = sync_until_stuck(team_queries, dag)
            synced += len(nodes)
            for saved_query, error in unresolved.items():
                if not isinstance(error, ADOPTABLE_SYNC_ERRORS):
                    failed += 1
                    self.stderr.write(f"  team {team_id}: FAILED {saved_query.name}, re-run to retry: {error!r}")
                    continue
                adopt_saved_query_without_edges(saved_query.team_id, saved_query.id, str(error), dag_id=dag.id)
                nodes.append(Node.objects.get(saved_query=saved_query, dag=dag))
                adopted += 1
                self.stderr.write(f"  team {team_id}: adopted {saved_query.name} without edges: {error}")
            seeded += seed_materialized_targets(nodes, dag)
            maybe_reconcile_dag(dag)
        self.stdout.write(f"Synced {synced}, adopted without edges {adopted}, failed {failed}, seeded targets {seeded}")


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


def sync_until_stuck(
    saved_queries: Iterable[DataWarehouseSavedQuery], dag: DAG
) -> tuple[list[Node], dict[DataWarehouseSavedQuery, Exception]]:
    pending = list(saved_queries)
    nodes: list[Node] = []
    while True:
        failures: dict[DataWarehouseSavedQuery, Exception] = {}
        for saved_query in pending:
            try:
                node = sync_saved_query_to_dag(saved_query, dag=dag, reconcile=False)
            except Exception as error:
                failures[saved_query] = error
                continue
            if node is not None:
                nodes.append(node)
        if not failures or len(failures) == len(pending):
            return nodes, failures
        pending = list(failures)


def seed_materialized_targets(nodes: Iterable[Node], dag: DAG) -> int:
    seeded = 0
    for node in nodes:
        if node.type not in MATERIALIZING_TYPES or get_declared_target(node) is not None:
            continue
        assert node.saved_query is not None
        set_declared_target(
            node, node.saved_query.sync_frequency_interval or dag.sync_frequency_interval or DEFAULT_MATERIALIZED_TARGET
        )
        seeded += 1
    return seeded
