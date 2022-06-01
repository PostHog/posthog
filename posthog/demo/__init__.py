from typing import cast

from rest_framework.request import Request

from posthog.demo.app_data_generator import AppDataGenerator
from posthog.demo.revenue_data_generator import RevenueDataGenerator
from posthog.demo.web_data_generator import WebDataGenerator
from posthog.models import EventDefinition, Organization, Team, User
from posthog.utils import render_template

ORGANIZATION_NAME = "Hogflix"
TEAM_NAME = "Hogflix Demo App"


def demo_route(request: Request):
    user = cast(User, request.user)
    organization = user.organization

    if not organization:
        raise AttributeError("This user has no organization.")

    try:
        team = organization.teams.get(is_demo=True)
    except Team.DoesNotExist:
        team = create_demo_team(organization, user, request)

    user.current_team = team
    user.save()
    EventDefinition.objects.get_or_create(team=team, name="$pageview")

    from posthog.models.event.util import get_events_by_team

    result = get_events_by_team(team_id=team.pk)
    if not result:
        create_demo_data(team, dashboards=False)

    return render_template("demo.html", request=request, context={"api_token": team.api_token})


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
