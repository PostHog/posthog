from collections import defaultdict
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import QuerySet

import structlog

from products.data_modeling.backend.logic.saved_query_dag_sync import (
    retire_stale_managed_view_copies,
    stale_managed_view_copies,
)
from products.data_modeling.backend.models.node import Node

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Move readers of stale managed-view copies onto the cross-DAG reference, then delete the copies. "
        "Dry run unless --apply."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only clean up this team")
        parser.add_argument("--apply", action="store_true", default=False, help="Repoint and delete instead of listing")

    def handle(self, *args: Any, **options: Any) -> None:
        copy_ids_by_team = self._find_copies(options["team_id"])
        copy_count = sum(len(copy_ids) for copy_ids in copy_ids_by_team.values())
        self.stdout.write(f"{copy_count} stale managed view copies in {len(copy_ids_by_team)} team(s)")
        if not options["apply"]:
            return

        failed_team_ids: list[int] = []
        for team_id, copy_ids in copy_ids_by_team.items():
            try:
                retire_stale_managed_view_copies(team_id, copy_ids)
            except Exception:
                logger.exception("Could not retire stale managed view copies", team_id=team_id)
                failed_team_ids.append(team_id)
        self.stdout.write(f"Done. {self._copies(options['team_id']).count()} copies remain")
        if failed_team_ids:
            self.stderr.write(f"Failed for team(s): {', '.join(str(team_id) for team_id in failed_team_ids)}")

    def _copies(self, team_id: int | None) -> QuerySet[Node]:
        copies = stale_managed_view_copies()
        if team_id is not None:
            copies = copies.filter(team_id=team_id)
        return copies

    def _find_copies(self, team_id: int | None) -> dict[int, list[UUID]]:
        copies = self._copies(team_id)
        copy_ids_by_team: dict[int, list[UUID]] = defaultdict(list)
        for node_id, node_team_id, dag_id, name in copies.values_list("id", "team_id", "dag_id", "name").iterator():
            self.stdout.write(f"team={node_team_id} dag={dag_id} node={node_id} name={name}")
            copy_ids_by_team[node_team_id].append(node_id)
        return copy_ids_by_team
