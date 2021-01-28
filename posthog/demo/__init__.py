from rest_framework.request import Request

from posthog.demo.app_data_generator import AppDataGenerator
from posthog.demo.revenue_data_generator import RevenueDataGenerator
from posthog.demo.web_data_generator import WebDataGenerator
from posthog.ee import is_ee_enabled
from posthog.models import Organization, Team, User
from posthog.utils import render_template

ORGANIZATION_NAME = "HogFlix"
TEAM_NAME = "HogFlix Demo App"


def demo(request: Request):
    user = request.user
    organization = user.organization
    try:
        team = organization.teams.get(is_demo=True)
    except Team.DoesNotExist:
        team = create_demo_team(organization, user, request)
    user.current_team = team
    user.save()

    if "$pageview" not in team.event_names:
        team.event_names.append("$pageview")
        team.event_names_with_usage.append({"event": "$pageview", "usage_count": None, "volume": None})
        team.save()

    if is_ee_enabled():  # :TRICKY: Lazily backfill missing event data.
        from ee.clickhouse.models.event import get_events_by_team

        result = get_events_by_team(team_id=team.pk)
        if not result:
            create_demo_data(team, dashboards=False)

    return render_template("demo.html", request=request, context={"api_token": team.api_token})


def create_demo_team(organization: Organization, user: User, request: Request) -> Team:
    team = Team.objects.create_with_data(
        organization=organization, name=TEAM_NAME, ingested_event=True, completed_snippet_onboarding=True, is_demo=True,
    )
    create_demo_data(team)
    return team


def create_demo_data(team: Team, dashboards=True):
    WebDataGenerator(team, n_people=40).create(dashboards=dashboards)
    AppDataGenerator(team, n_people=100).create(dashboards=dashboards)
    RevenueDataGenerator(team, n_people=20).create(dashboards=dashboards)
