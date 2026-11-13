"""The command-line surface a source shares for copying each alert's creation time onto its platform copy.

Each source keeps its own command module, so `manage.py` finds it by name, and subclasses this to
name the model whose rows record when each alert was created.
"""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Model

import structlog

from products.alerts_platform.backend.facade.api import match_created_at, team_ids_with_copies
from products.alerts_platform.backend.facade.contracts import SourceKind

logger = structlog.get_logger(__name__)


def add_copy_backfill_arguments(parser: Any) -> None:
    """`--team-id` and `--apply`, shared by the commands that match copies to their source rows."""
    parser.add_argument(
        "--team-id", type=int, action="append", dest="team_ids", help="Only this team. Repeat for more."
    )
    parser.add_argument("--apply", action="store_true", help="Write the changes. Without it, only count them.")


class PlatformCreatedAtBackfillCommand(BaseCommand):
    source_kind: SourceKind
    source_model: type[Model]

    def created_at_of(self, team_id: int, ids: Collection[UUID]) -> Mapping[UUID, datetime]:
        rows = self.source_model._default_manager.filter(team_id=team_id, id__in=ids)
        return dict(rows.values_list("id", "created_at"))

    def add_arguments(self, parser: Any) -> None:
        add_copy_backfill_arguments(parser)

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = not options["apply"]
        verb = "Would set" if dry_run else "Set"
        team_ids = options["team_ids"] or team_ids_with_copies(self.source_kind)
        matched = 0
        failed: list[int] = []
        # One team at a time, so one team's failure leaves the rest done and a rerun skips what matches.
        for team_id in team_ids:
            try:
                count = match_created_at(
                    source_kind=self.source_kind,
                    team_id=team_id,
                    created_at_of=lambda ids, team_id=team_id: self.created_at_of(team_id, ids),
                    dry_run=dry_run,
                )
            except Exception:
                logger.exception("platform_copy_created_at_backfill.failed", team_id=team_id)
                failed.append(team_id)
                continue
            matched += count
            if count:
                self.stdout.write(f"Team {team_id}: {verb.lower()} created_at on {count} copies")
        self.stdout.write(f"{verb} created_at on {matched} {self.source_kind.value} platform copies")
        if failed:
            raise CommandError(f"Failed for teams: {', '.join(map(str, failed))}")
