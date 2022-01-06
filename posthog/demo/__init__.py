from typing import Any, Dict, Optional, Tuple, cast

from rest_framework.request import Request

from posthog.demo.app_data_generator import AppDataGenerator
from posthog.demo.revenue_data_generator import RevenueDataGenerator
from posthog.demo.web_data_generator import WebDataGenerator
from posthog.models import EventDefinition, Organization, OrganizationMembership, Team, User
from posthog.utils import is_clickhouse_enabled, render_template

from . import hoglify

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

    if is_clickhouse_enabled():  # :TRICKY: Lazily backfill missing event data.
        from ee.clickhouse.models.event import get_events_by_team

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


def prepare_hoglify_demo(
    *,
    email: str,
    first_name: str,
    password: Optional[str] = None,
    organization_name: str = None,
    team_fields: Optional[Dict[str, Any]] = None,
    no_data: bool = False,
) -> Tuple[Organization, Team, User]:
    # If there's an email collision in signup in the demo environment, we treat it as a login
    existing_user = User.objects.filter(email=email).first()
    if existing_user is None:
        organization = Organization.objects.create(name=organization_name or hoglify.ORGANIZATION_NAME)
        new_user = User.objects.create_and_join(
            organization, email, password, first_name, OrganizationMembership.Level.ADMIN
        )
        team = hoglify.hoglify_data_generator.create_team(
            organization, new_user, simulate_journeys=not no_data, **(team_fields or {})
        )
        return organization, team, new_user
    else:
        return existing_user.organization, existing_user.team, existing_user
