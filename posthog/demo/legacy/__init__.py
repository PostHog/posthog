from posthog.models import EventDefinition, Organization, Team

from .app_data_generator import AppDataGenerator
from .revenue_data_generator import RevenueDataGenerator
from .web_data_generator import WebDataGenerator

ORGANIZATION_NAME = "Hogflix"
TEAM_NAME = "Hogflix Demo App"


def create_demo_team(organization: Organization, *args) -> Team:
    team = Team.objects.create_with_data(
        default_dashboards=False,
        organization=organization,
        name=TEAM_NAME,
        ingested_event=True,
        completed_snippet_onboarding=True,
        session_recording_opt_in=True,
        is_demo=True,
    )
    create_demo_data(team)
    EventDefinition.objects.get_or_create(team=team, name="$pageview")
    return team


def create_demo_data(team: Team, dashboards=True):
    WebDataGenerator(team, n_people=40).create(dashboards=dashboards)
    AppDataGenerator(team, n_people=100).create(dashboards=dashboards)
    RevenueDataGenerator(team, n_people=20).create(dashboards=dashboards)
