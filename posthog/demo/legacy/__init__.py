from typing import cast

from django.http import HttpRequest

from posthog.models import EventDefinition, Organization, Team, User
from posthog.utils import render_template

from .app_data_generator import AppDataGenerator
from .revenue_data_generator import RevenueDataGenerator
from .web_data_generator import WebDataGenerator

ORGANIZATION_NAME = "Hogflix"
TEAM_NAME = "Hogflix Demo App"


def demo_route(request: HttpRequest):
    user = cast(User, request.user)  # The user must be logged in because of login_required()
    project_api_token = user.team.api_token if user.team is not None else None
    return render_template("demo.html", request=request, context={"api_token": project_api_token})


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
