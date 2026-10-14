from posthog.models import Team

from .app_data_generator import AppDataGenerator
from .insight_variables_data_generator import InsightVariablesDataGenerator
from .revenue_data_generator import RevenueDataGenerator
from .web_data_generator import WebDataGenerator

ORGANIZATION_NAME = "Hogflix"
TEAM_NAME = "Hogflix Demo App"


def create_demo_data(team: Team, dashboards=True):
    WebDataGenerator(team, n_people=40).create(dashboards=dashboards)
    AppDataGenerator(team, n_people=100).create(dashboards=dashboards)
    RevenueDataGenerator(team, n_people=20).create(dashboards=dashboards)

    # Product analytics e2e tests
    InsightVariablesDataGenerator(team).create(dashboards=dashboards)
