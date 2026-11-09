import datetime

from django.db.models import Model

from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Panel, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


def _when(value: datetime.datetime | None) -> str:
    return value.strftime("%b %-d, %Y") if value else "Never"


@console.register_panel
class UserOverviewPanel(Panel):
    record = "user"
    key = "overview"
    title = "Overview"
    owner = DEV_EXPERIENCE

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, User)
        facts = [
            Fact(label="Status", value="Active", tone=Tone.SUCCESS)
            if obj.is_active
            else Fact(label="Status", value="Deactivated", tone=Tone.DESTRUCTIVE),
            Fact(label="Joined", value=_when(obj.date_joined)),
            Fact(label="Last login", value=_when(obj.last_login)),
        ]
        if obj.current_organization is not None:
            facts.append(
                Fact(
                    label="Current organization",
                    value=obj.current_organization.name,
                    href=RECORD_TYPES["organization"].url(obj.current_organization),
                )
            )
        if obj.current_team is not None:
            facts.append(
                Fact(label="Current team", value=obj.current_team.name, href=RECORD_TYPES["team"].url(obj.current_team))
            )
        if obj.is_staff:
            facts.append(Fact(label="Staff", value="Yes", tone=Tone.INFO))
        if obj.allow_impersonation is False:
            facts.append(Fact(label="Log in as user", value="Turned off by the user"))
        return facts


@console.register_panel
class UserOrganizationsPanel(Panel):
    record = "user"
    key = "organizations"
    title = "Organizations"
    owner = DEV_EXPERIENCE

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, User)
        memberships = list(
            OrganizationMembership.objects.filter(user=obj)
            .select_related("organization")
            .order_by("joined_at")[: MAX_FACTS_PER_PANEL + 1]
        )
        if not memberships:
            return [Fact(label="Organizations", value="This user is in no organization.")]
        shown = memberships if len(memberships) <= MAX_FACTS_PER_PANEL else memberships[: MAX_FACTS_PER_PANEL - 1]
        organization_record = RECORD_TYPES["organization"]
        facts = [
            Fact(
                label=membership.organization.name,
                value=OrganizationMembership.Level(membership.level).label.capitalize(),
                href=organization_record.url(membership.organization),
            )
            for membership in shown
        ]
        if len(shown) < len(memberships):
            hidden = OrganizationMembership.objects.filter(user=obj).count() - len(shown)
            facts.append(
                Fact(label="More", value=f"{hidden} more organizations. The raw record in Django admin lists all.")
            )
        return facts
