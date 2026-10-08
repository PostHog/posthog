from typing import Any

from django.core.management.base import BaseCommand

from products.access_control.backend.facade.most_specific_migration import (
    MigrationCandidates,
    enable_most_specific_resolution,
    find_organizations_to_migrate,
)


class Command(BaseCommand):
    help = "Switch organizations that the most-specific access resolution does not affect over to it"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report only, migrate nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        candidates = find_organizations_to_migrate()
        self._report(candidates)

        unaffected_ids = candidates.unaffected_ids
        if options["dry_run"]:
            self.stdout.write(f"Dry run: {len(unaffected_ids)} organizations would be migrated")
            return
        updated = enable_most_specific_resolution(unaffected_ids, rules_unchanged_since=candidates.found_at)
        self.stdout.write(f"Migrated {updated} organizations")
        if updated < len(unaffected_ids):
            self.stdout.write(
                f"{len(unaffected_ids) - updated} organizations skipped because their rules changed during the run"
            )

    def _report(self, candidates: MigrationCandidates) -> None:
        self.stdout.write(
            f"{len(candidates.divergent)} organizations resolve differently (stay on the legacy resolution)"
        )
        for org in candidates.divergent:
            self.stdout.write(
                f"{org.id}\t{org.name}\tteams={org.teams}\tchanges={org.changes}\tgains={org.gains}\tloses={org.loses}"
            )

        self.stdout.write("")
        self.stdout.write(f"{len(candidates.unchanged)} organizations with rules where nothing changes")
        for org in candidates.unchanged:
            self.stdout.write(f"{org.id}\t{org.name}\tteams={org.teams}")

        self.stdout.write("")
        self.stdout.write(
            f"{len(candidates.unevaluated)} organizations could not be evaluated (no active member, stay on the legacy resolution)"
        )
        for ref in candidates.unevaluated:
            self.stdout.write(f"{ref.id}\t{ref.name}")

        self.stdout.write("")
        self.stdout.write(f"{len(candidates.without_rules)} organizations with no access rules")
        self.stdout.write("")
