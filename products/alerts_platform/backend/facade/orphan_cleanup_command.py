"""The command-line surface a source shares for deleting shadow copies whose source row is gone.

Each source keeps its own command module, so `manage.py` finds it by name, and subclasses this to
say which of its rows still exist.
"""

from collections.abc import Collection
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand

from products.alerts_platform.backend.facade.api import delete_orphaned_shadow_copies
from products.alerts_platform.backend.facade.contracts import SourceKind


class PlatformOrphanCleanupCommand(BaseCommand):
    source_kind: SourceKind

    def existing_source_ids(self, ids: Collection[UUID]) -> Collection[UUID]:
        raise NotImplementedError

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count the orphaned copies and delete nothing.")

    def handle(self, *args: Any, **options: Any) -> None:
        count = delete_orphaned_shadow_copies(
            source_kind=self.source_kind, existing_source_ids=self.existing_source_ids, dry_run=options["dry_run"]
        )
        verb = "Would delete" if options["dry_run"] else "Deleted"
        self.stdout.write(f"{verb} {count} {self.source_kind.value} shadow copies with no source row")
