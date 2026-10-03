from typing import Any

from django.core.management.base import BaseCommand

from products.access_control.backend.facade.resolution_preview import ResolutionChange, iter_resolution_changes


class Command(BaseCommand):
    help = (
        "Show what changes for one organization under most-specific access resolution: "
        "every rule that resolves differently, per project. Read-only."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("organization_id")

    def handle(self, *args: Any, **options: Any) -> None:
        detail_lines: list[str] = []
        teams = 0
        gains = 0
        loses = 0
        organization_name = ""

        for team, changes in iter_resolution_changes(options["organization_id"]):
            teams += 1
            organization_name = team.organization.name
            gains += sum(1 for change in changes if change.direction == "gains")
            loses += sum(1 for change in changes if change.direction == "loses")
            detail_lines.append(f"Project {team.pk} — {team.name}")
            if not changes:
                detail_lines.append("  no changes")
            for change in changes:
                detail_lines.append(f"  {self._describe(change)}")

        if teams == 0:
            self.stdout.write("No access rules found for this organization.")
            return

        changes_total = gains + loses
        if changes_total > 0:
            summary = f"changes={changes_total}\tgains={gains}\tloses={loses}"
        else:
            summary = "no changes"
        self.stdout.write(f"organization\t{organization_name}\tteams={teams}\t{summary}")
        self.stdout.write("")
        for line in detail_lines:
            self.stdout.write(line)

    def _describe(self, change: ResolutionChange) -> str:
        if change.scope == "resource":
            target = f"all {change.resource}s"
        else:
            target = f'{change.resource} "{change.object_name or change.object_id}"'
        return (
            f"{change.subject.type} {change.subject.name}\t{target}\t"
            f"{change.current.access_level} -> {change.proposed.access_level} ({change.direction})"
        )
