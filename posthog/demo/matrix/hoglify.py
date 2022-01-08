"""Simulation of users of a product called Hoglify.

Hoglify is one of the leading providers of static hosting/serverless services.
It caters to individual developers and teams of all sizes, but most of its revenue comes from large orgs.

The strategy of simulating Hoglify uses clusters that initially consist just of one kernel person.
If this person is employed though, they may cause their organization to start using the product too.
This way the product becomes organically ingrained in teams.

Each kernel person is of a random archetype:
- The student - will only use themselves, won't become paying (max size 1).
    There are few of them and they are of low value.
- The professsional - will start out themselves for free, but may also upgrade and there is a chance they become
    an advocate, in which case they may get their org to use it (max size 1). They are many of them
    and they are of moderate value.
- The procurer - is looking for a solution to apply at their org, after a small initial trial they either churn
    or become paying. There are few of them and they are of high value.
Non-kernel persons are all classified as drone persons. Drones are users in their own right, but they only
affect the org via network effects (i.e. the more users there are, the more entrenched the product is),
not advocacy or decision-making.

In each cluster there are one OR two projects, at most one of each category:
- personal - belongs to an individual user, worked on:
    - between 6 PM and 12 AM on work days, sporadically
    - between 12 PM and 12 AM on weekends, sporadically
- organization - belongs to the entire cluster, worked on:
    - between 8 PM nad 6 PM on work days, intensely

Cluster activity is tracked with an event loop for effective asynchronicity.

Extra premises:
- There's an experiment running for a new signup page flow. The new signup page does result in more signups.
- Most revenue comes from a few large teams.
- There are many individuals using the product for free.
- A significant fraction of users never deploy anything.
- Frequency of deploys correlates with outlay.
- Teams are far more likely to become paying users.
- 12% of users (professsionals most often) opt into the beta program.
"""

import datetime as dt
import random
from typing import Any, Dict, Generator, Optional, Tuple, Type

from posthog.models import Dashboard, FeatureFlag, Insight, Team, User
from posthog.models.utils import UUIDT

from .models import Effect, SimGroup, SimPerson
from .randomization import (
    address_provider,
    datetime_provider,
    internet_provider,
    numeric_provider,
    person_provider,
    properties_provider,
)
from .simulation import Cluster, Matrix

ORGANIZATION_NAME = "Hoglify Inc."
TEAM_NAME = "Hoglify"

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


class HoglifyPerson(SimPerson):
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


class HoglifyMatrix(Matrix):
    def make_cluster(self) -> Cluster:
        return Cluster(start=self.start, end=self.end, min_root_size=1, max_root_size=15, person_model=HoglifyPerson)

    def set_project_up(self, team: Team, user: User):
        from ee.models.event_definition import EnterpriseEventDefinition
        from ee.models.property_definition import EnterprisePropertyDefinition

        team.name = TEAM_NAME
        team.session_recording_opt_in = True
        team.save()

        # Taxonomy
        ## Signup
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
        ## Core product
        ## Revenue
        ## NPS
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
