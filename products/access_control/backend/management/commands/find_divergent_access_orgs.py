from typing import Any

from django.core.management.base import BaseCommand

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.resolution_preview import build_resolution_preview


class Command(BaseCommand):
    help = (
        "List organizations whose access resolution differs under most-specific-wins (RFC 557). "
        "The output feeds the preview feature flag targeting; organizations not listed can move "
        "to the new resolution without a visible change."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--all", action="store_true", help="Also print organizations with no differences")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = AccessControl.objects.values_list("team_id", flat=True).distinct()
        teams = Team.objects.filter(id__in=team_ids).select_related("organization").order_by("organization_id")

        acting_membership_by_org: dict[Any, OrganizationMembership] = {}
        totals: dict[Any, dict[str, int]] = {}
        names: dict[Any, str] = {}

        for team in teams.iterator():
            org_id = team.organization_id
            names[org_id] = team.organization.name
            membership = acting_membership_by_org.get(org_id)
            if membership is None:
                membership = (
                    OrganizationMembership.objects.filter(organization_id=org_id, user__is_active=True)
                    .select_related("user")
                    .first()
                )
                if membership is None:
                    continue
                acting_membership_by_org[org_id] = membership

            changes = build_resolution_preview(team, UserAccessControl(membership.user, team))
            counts = totals.setdefault(org_id, {"teams": 0, "changes": 0, "gains": 0, "loses": 0})
            counts["teams"] += 1
            counts["changes"] += len(changes)
            counts["gains"] += sum(1 for change in changes if change.direction == "gains")
            counts["loses"] += sum(1 for change in changes if change.direction == "loses")

        divergent = 0
        for org_id, counts in sorted(totals.items(), key=lambda item: -item[1]["changes"]):
            if counts["changes"] == 0 and not options["all"]:
                continue
            if counts["changes"] > 0:
                divergent += 1
            self.stdout.write(
                f"{org_id}\t{names[org_id]}\tteams={counts['teams']}\t"
                f"changes={counts['changes']}\tgains={counts['gains']}\tloses={counts['loses']}"
            )
        self.stdout.write(f"# {divergent} divergent organizations out of {len(totals)} with access rules")
