from collections import defaultdict
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import QuerySet

from products.data_modeling.backend.logic.saved_query_dag_sync import (
    delete_deleted_saved_query_nodes_for_teams,
    deleted_saved_query_nodes,
)
from products.data_modeling.backend.models.node import Node


class Command(BaseCommand):
    help = "Delete the DAG nodes of soft-deleted saved queries. Dry run unless --apply."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only clean up this team")
        parser.add_argument("--apply", action="store_true", default=False, help="Delete instead of listing")

    def handle(self, *args: Any, **options: Any) -> None:
        node_ids_by_team = self._find_nodes(options["team_id"])
        node_count = sum(len(node_ids) for node_ids in node_ids_by_team.values())
        self.stdout.write(f"{node_count} node(s) of deleted saved queries in {len(node_ids_by_team)} team(s)")
        if not options["apply"]:
            return

        failed_team_ids = delete_deleted_saved_query_nodes_for_teams(node_ids_by_team.keys())
        self.stdout.write(f"Done. {self._nodes(options['team_id']).count()} node(s) remain")
        if failed_team_ids:
            self.stderr.write(f"Failed for team(s): {', '.join(str(team_id) for team_id in failed_team_ids)}")

    def _nodes(self, team_id: int | None) -> QuerySet[Node]:
        nodes = deleted_saved_query_nodes()
        if team_id is not None:
            nodes = nodes.filter(team_id=team_id)
        return nodes

    def _find_nodes(self, team_id: int | None) -> dict[int, list[UUID]]:
        node_ids_by_team: dict[int, list[UUID]] = defaultdict(list)
        rows = self._nodes(team_id).values_list("id", "team_id", "dag_id", "saved_query_id").iterator()
        for node_id, node_team_id, dag_id, saved_query_id in rows:
            self.stdout.write(f"team={node_team_id} dag={dag_id} node={node_id} saved_query={saved_query_id}")
            node_ids_by_team[node_team_id].append(node_id)
        return node_ids_by_team
