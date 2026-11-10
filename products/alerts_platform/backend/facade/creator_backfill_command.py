"""The command-line surface a source shares for copying each alert's creator onto its platform copy.

Each source keeps its own command module, so `manage.py` finds it by name, and subclasses this to
name the model whose rows record who created each alert.
"""

from collections.abc import Collection, Mapping
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db.models import Model

from products.alerts_platform.backend.facade.api import fill_missing_creators
from products.alerts_platform.backend.facade.contracts import SourceKind


class PlatformCreatorBackfillCommand(BaseCommand):
    source_kind: SourceKind
    source_model: type[Model]

    def creators_of(self, ids: Collection[UUID]) -> Mapping[UUID, int]:
        # nosemgrep: idor-lookup-without-team
        rows = self.source_model._default_manager.filter(id__in=ids, created_by__isnull=False)
        return dict(rows.values_list("id", "created_by_id"))

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count the copies to fill and write nothing.")

    def handle(self, *args: Any, **options: Any) -> None:
        count = fill_missing_creators(
            source_kind=self.source_kind, creators_of=self.creators_of, dry_run=options["dry_run"]
        )
        verb = "Would fill" if options["dry_run"] else "Filled"
        self.stdout.write(f"{verb} the creator on {count} {self.source_kind.value} platform copies")
