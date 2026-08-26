from typing import Any

from django.core.management.base import BaseCommand

from products.access_control.backend.resolution_preview import iter_resolution_changes


class Command(BaseCommand):
    help = (
        "Report readiness for most-specific access resolution across organizations that have access "
        "rules: those that resolve differently first, then those where nothing changes. Organizations "
        "with no rules cannot resolve differently and are omitted, and an organization with no active "
        "member is skipped. Read-only for now; migration comes later, so --dry-run and a plain run "
        "print the same report."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report only, migrate nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        totals: dict[Any, dict[str, int]] = {}
        names: dict[Any, str] = {}

        for team, changes in iter_resolution_changes():
            org_id = team.organization_id
            names[org_id] = team.organization.name
            counts = totals.setdefault(org_id, {"teams": 0, "changes": 0, "gains": 0, "loses": 0})
            counts["teams"] += 1
            counts["changes"] += len(changes)
            counts["gains"] += sum(1 for change in changes if change.direction == "gains")
            counts["loses"] += sum(1 for change in changes if change.direction == "loses")

        divergent = {org_id: counts for org_id, counts in totals.items() if counts["changes"] > 0}
        unchanged = {org_id: counts for org_id, counts in totals.items() if counts["changes"] == 0}

        self.stdout.write(f"{len(divergent)} organizations resolve differently")
        for org_id, counts in sorted(divergent.items(), key=lambda item: -item[1]["changes"]):
            self.stdout.write(
                f"{org_id}\t{names[org_id]}\tteams={counts['teams']}\t"
                f"changes={counts['changes']}\tgains={counts['gains']}\tloses={counts['loses']}"
            )

        self.stdout.write("")
        self.stdout.write(f"{len(unchanged)} organizations where nothing changes")
        for org_id, counts in sorted(unchanged.items(), key=lambda item: str(item[0])):
            self.stdout.write(f"{org_id}\t{names[org_id]}\tteams={counts['teams']}")
