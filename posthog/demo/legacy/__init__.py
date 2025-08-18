from typing import cast

from django.http import HttpRequest

from posthog.models import Team, User
from posthog.utils import render_template

from .app_data_generator import AppDataGenerator
from .insight_variables_data_generator import InsightVariablesDataGenerator
from .revenue_data_generator import RevenueDataGenerator
from .web_data_generator import WebDataGenerator

ORGANIZATION_NAME = "Hogflix"
TEAM_NAME = "Hogflix Demo App"


def demo_route(request: HttpRequest):
    user = cast(User, request.user)  # The user must be logged in because of login_required()
    project_api_token = user.team.api_token if user.team is not None else None
    return render_template("demo.html", request=request, context={"api_token": project_api_token})


def create_demo_data(team: Team, dashboards=True):
    WebDataGenerator(team, n_people=40).create(dashboards=dashboards)
    AppDataGenerator(team, n_people=100).create(dashboards=dashboards)
    RevenueDataGenerator(team, n_people=20).create(dashboards=dashboards)

    # Product analytics e2e tests
    InsightVariablesDataGenerator(team).create(dashboards=dashboards)
