from django.db.models import Model

from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Panel
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.models.project import Project


@console.register_panel
class ProjectOverviewPanel(Panel):
    record = "project"
    key = "overview"
    title = "Overview"
    owner = DEV_EXPERIENCE

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Project)
        facts = [
            Fact(
                label="Organization",
                value=obj.organization.name,
                href=RECORD_TYPES["organization"].url(obj.organization),
            ),
            Fact(label="Created", value=obj.created_at.strftime("%b %-d, %Y")),
        ]
        room = MAX_FACTS_PER_PANEL - len(facts)
        team_record = RECORD_TYPES["team"]
        teams = list(obj.teams.order_by("id").only("id", "name")[: room + 1])
        if not teams:
            return [*facts, Fact(label="Teams", value="This project has no teams.")]
        shown = teams if len(teams) <= room else teams[: room - 1]
        facts += [
            Fact(label=team.name, value=f"Team {team.pk}", mono=True, href=team_record.url(team)) for team in shown
        ]
        if len(shown) < len(teams):
            hidden = obj.teams.count() - len(shown)
            facts.append(Fact(label="More", value=f"{hidden} more teams. The raw record in Django admin lists all."))
        return facts
