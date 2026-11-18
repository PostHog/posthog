from collections import defaultdict
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from products.data_modeling.backend.logic.saved_query_dag_sync import (
    delete_orphaned_table_nodes,
    lock_dag,
    orphaned_table_nodes,
)


class Command(BaseCommand):
    help = "Delete DAG table nodes that no view or metric reads any more. Dry run unless --apply."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only clean up this team")
        parser.add_argument("--apply", action="store_true", default=False, help="Delete instead of listing")

    def handle(self, *args: Any, **options: Any) -> None:
        node_ids_by_dag = self._find_orphans(options["team_id"])
        orphan_count = sum(len(node_ids) for node_ids in node_ids_by_dag.values())
        self.stdout.write(f"{orphan_count} orphaned table node(s) in {len(node_ids_by_dag)} DAG(s)")
        if not options["apply"]:
            return

        for (team_id, dag_id), node_ids in node_ids_by_dag.items():
            with transaction.atomic():
                lock_dag(team_id, dag_id)
                delete_orphaned_table_nodes(team_id, node_ids)
        self.stdout.write("Deleted")

    def _find_orphans(self, team_id: int | None) -> dict[tuple[int, UUID], list[UUID]]:
        orphans = orphaned_table_nodes()
        if team_id is not None:
            orphans = orphans.filter(team_id=team_id)

        node_ids_by_dag: dict[tuple[int, UUID], list[UUID]] = defaultdict(list)
        for node_id, node_team_id, dag_id, name in orphans.values_list("id", "team_id", "dag_id", "name").iterator():
            self.stdout.write(f"team={node_team_id} dag={dag_id} node={node_id} name={name}")
            node_ids_by_dag[(node_team_id, dag_id)].append(node_id)
        return node_ids_by_dag
