from typing import Any

from django.core.management.base import BaseCommand

from products.access_control.backend.facade.resolution_migration import (
    ResolutionSweep,
    enable_most_specific_resolution,
    sweep_pending_organizations,
)


class Command(BaseCommand):
    help = (
        "Switch organizations that the most-specific access resolution cannot affect over to it: "
        "those whose access rules resolve the same under both resolutions, and those with no "
        "rules. Organizations that resolve differently, and organizations with rules but no "
        "active member to evaluate as, are reported and left on the legacy resolution. "
        "Organizations already on the most-specific resolution are skipped."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report only, migrate nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        sweep = sweep_pending_organizations()
        self._report(sweep)

        unaffected_ids = sweep.unaffected_ids
        if options["dry_run"]:
            self.stdout.write(f"Dry run: {len(unaffected_ids)} organizations would be migrated")
            return
        updated = enable_most_specific_resolution(unaffected_ids)
        self.stdout.write(f"Migrated {updated} organizations")

    def _report(self, sweep: ResolutionSweep) -> None:
        self.stdout.write(f"{len(sweep.divergent)} organizations resolve differently (left on the legacy resolution)")
        for readiness in sweep.divergent:
            self.stdout.write(
                f"{readiness.id}\t{readiness.name}\tteams={readiness.teams}\t"
                f"changes={readiness.changes}\tgains={readiness.gains}\tloses={readiness.loses}"
            )

        self.stdout.write("")
        self.stdout.write(f"{len(sweep.unchanged)} organizations with rules where nothing changes")
        for readiness in sweep.unchanged:
            self.stdout.write(f"{readiness.id}\t{readiness.name}\tteams={readiness.teams}")

        self.stdout.write("")
        self.stdout.write(
            f"{len(sweep.unevaluated)} organizations could not be evaluated (no active member, left on the legacy resolution)"
        )
        for ref in sweep.unevaluated:
            self.stdout.write(f"{ref.id}\t{ref.name}")

        self.stdout.write("")
        self.stdout.write(f"{len(sweep.without_rules)} organizations with no access rules")
        self.stdout.write("")
