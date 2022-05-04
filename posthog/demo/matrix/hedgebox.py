"""Simulation of users of a product called Hedgebox.
"""

import datetime as dt
import random
from typing import Any, Dict, Generator, Optional, Tuple

from posthog.models import Dashboard, FeatureFlag, Insight, Team, User

from .models import Effect, SimPerson
from .randomization import internet_provider, person_provider, properties_provider
from .simulation import Cluster, Matrix

ORGANIZATION_NAME = "Hedgebox Inc."
TEAM_NAME = "Hedgebox"

SIGNUP_PAGE_FLAG_KEY = "signup-page-4.0"
SIGNUP_PAGE_FLAG_ROLLOUT = 0.5

EVENT_SIGNUP_ENTERED = "signup_entered"
EVENT_SIGNUP_COMPLETED = "signup_completed"
EVENT_SUBSCRIPTION_PAID = "subscription_paid"
EVENT_SUBSCRIPTION_CANCELED = "subscription_canceled"
EVENT_NPS_SURVEY = "nps_survey"

PROPERTY_PLAN = "plan"
PROPERTY_AMOUNT_USD = "amount_usd"
PROPERTY_NPS_RATING = "nps_rating"


class HedgeboxPerson(SimPerson):
    device_type: str
    os: str
    browser: str
    ip: str
    email: str

    def __init__(self):
        super().__init__()
        self.device_type, self.os, self.browser = properties_provider.device_type_os_browser()
        self.ip = internet_provider.ip_v4()
        self.email = person_provider.email()

    def derive_base_properties(self) -> Dict[str, Any]:
        return {
            "$device_type": self.device_type,
            "$os": self.os,
            "$browser": self.browser,
            "$ip": self.ip,
            "$current_url": "https://posthog.com/",
            "$referrer": "https://www.google.com/",
            "$referring_domain": "www.google.com",
        }

    def sessions(
        self, initial_point_in_time: dt.datetime
    ) -> Generator[Tuple[dt.datetime, Optional[Effect]], dt.datetime, None]:
        point_in_time = initial_point_in_time
        # Signup session
        self.capture_event(EVENT_SIGNUP_ENTERED, point_in_time)
        point_in_time += dt.timedelta(seconds=random.randint(30, 90))
        self.capture_event(EVENT_SIGNUP_COMPLETED, point_in_time)
        point_in_time += dt.timedelta(seconds=random.randint(30, 90))
        point_in_time = yield (point_in_time, None)


class HedgeboxMatrix(Matrix):
    def make_cluster(self) -> Cluster:
        return Cluster(start=self.start, end=self.end, min_root_size=1, max_root_size=15, person_model=HedgeboxPerson)

    def set_project_up(self, team: Team, user: User):
        from ee.models.event_definition import EnterpriseEventDefinition
        from ee.models.property_definition import EnterprisePropertyDefinition

        team.name = TEAM_NAME
        team.session_recording_opt_in = True
        team.save()

        # Taxonomy
        # - Signup
        EnterpriseEventDefinition.objects.create(
            team=team, name=EVENT_SIGNUP_ENTERED, description="User entered signup flow"
        )
        EnterpriseEventDefinition.objects.create(team=team, name=EVENT_SIGNUP_COMPLETED, description="User signed up")
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_PLAN, description="Subcription plan: standard or ultra"
        )
        EnterpriseEventDefinition.objects.create(
            team=team, name=EVENT_SUBSCRIPTION_PAID, description="Subscription paid"
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_AMOUNT_USD, description="Amount paid in USD", is_numerical=True
        )
        EnterpriseEventDefinition.objects.create(
            team=team, name=EVENT_SUBSCRIPTION_CANCELED, description="Subscription canceled"
        )
        # - Core product
        # - Revenue
        # - NPS
        EnterpriseEventDefinition.objects.create(team=team, name=EVENT_NPS_SURVEY, description="An NPS survey answer")
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_NPS_RATING, description="0-10 rating given by user", is_numerical=True
        )

        # Dashboards
        key_metrics_dashboard = Dashboard.objects.create(
            team=team, name="Key metrics", description="Overview of company metrics.", pinned=True
        )

        # Insights
        Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            order=0,
            saved=True,
            name="Weekly signups",
            filters={
                "events": [{"id": EVENT_SIGNUP_COMPLETED, "type": "events", "order": 0}],
                "actions": [],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "week",
            },
        )

        # Feature flags
        FeatureFlag.objects.create(
            team=team,
            key=SIGNUP_PAGE_FLAG_KEY,
            name="New signup flow",
            rollout_percentage=SIGNUP_PAGE_FLAG_ROLLOUT * 100,
            created_by=user,
        )
