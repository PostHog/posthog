from typing import Any, Dict, Optional, Tuple, cast

from rest_framework.request import Request

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.utils import render_template

from . import hoglify
from .app_data_generator import AppDataGenerator
from .revenue_data_generator import RevenueDataGenerator
from .web_data_generator import WebDataGenerator


def prepare_demo(
    *,
    email: str,
    first_name: str,
    password: Optional[str] = None,
    organization_name: str = None,
    team_fields: Optional[Dict[str, Any]] = None,
    no_data: bool = False,
    legacy_generators: bool = False
) -> Tuple[Organization, Team, User]:
    # If there's an email collision in signup in the demo environment, we treat it as a login
    existing_user = User.objects.filter(email=email).first()
    if existing_user is None:
        organization = Organization.objects.create(
            name=organization_name or (hoglify.ORGANIZATION_NAME if not legacy_generators else "Hogflix")
        )
        new_user = User.objects.create_and_join(
            organization, email, password, first_name, OrganizationMembership.Level.ADMIN
        )
        if not legacy_generators:
            team = hoglify.hoglify_data_generator.create_team(
                organization, new_user, simulate_journeys=not no_data, **(team_fields or {})
            )
        else:
            team = WebDataGenerator(n_people=40).create_team(organization, new_user, simulate_journeys=not no_data)
            AppDataGenerator(n_people=100).run_on_team(team, new_user, simulate_journeys=not no_data)
            RevenueDataGenerator(n_people=20).run_on_team(team, new_user, simulate_journeys=not no_data)
        return organization, team, new_user
    else:
        return existing_user.organization, existing_user.team, existing_user


def demo_route(request: Request):
    user = cast(User, request.user)
    organization = user.organization

    if not organization:
        raise AttributeError("This user has no organization.")

    try:
        team = organization.teams.get(is_demo=True)
    except Team.DoesNotExist:
        team = WebDataGenerator(n_people=40).create_team(organization, user)
        AppDataGenerator(n_people=100).run_on_team(team, user)
        RevenueDataGenerator(n_people=20).run_on_team(team, user)

    user.current_team = team
    user.save()
    return render_template("demo.html", request=request, context={"api_token": team.api_token})
