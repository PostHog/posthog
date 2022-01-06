import datetime as dt
import math
from typing import Dict, List, Optional, Tuple

import mimesis
import mimesis.random

from posthog.demo.data_generator_v2 import DataGenerator, SimPerson
from posthog.models import Dashboard, FeatureFlag, Insight, Team, User

try:
    from ee.models.event_definition import EnterpriseEventDefinition
    from ee.models.property_definition import EnterprisePropertyDefinition
except ImportError:
    pass

ORGANIZATION_NAME = "Hoglify Inc."
TEAM_NAME = "Hoglify"

SIGNUP_PAGE_FLAG_KEY = "signup-page-4.0"
SIGNUP_PAGE_FLAG_ROLLOUT = 0.5

# Rate roughly determining how many out of all simulated users
# should be considered existing prior to the beginning of the sim
EXISTING_USERS_RATE = 0.7

EVENT_SIGNUP_ENTERED = "signup_entered"
EVENT_SIGNUP_COMPLETED = "signup_completed"
EVENT_SUBSCRIPTION_PAID = "subscription_paid"
EVENT_SUBSCRIPTION_CANCELED = "subscription_canceled"
EVENT_NPS_SURVEY = "nps_survey"

PROPERTY_PLAN = "plan"
PROPERTY_AMOUNT_USD = "amount_usd"
PROPERTY_NPS_RATING = "nps_rating"

WeightedPool = Tuple[List[str], List[int]]


class PropertiesProvider(mimesis.BaseProvider):
    DEVICE_TYPE_WEIGHTED_POOL: WeightedPool = (["Desktop", "Mobile", "Tablet"], [8, 1, 1])
    OS_WEIGHTED_POOLS: Dict[str, WeightedPool] = {
        "Desktop": (["Windows", "Mac OS X", "Linux", "Chrome OS"], [18, 16, 7, 1]),
        "Mobile": (["iOS", "Android"], [1, 1]),
        "Tablet": (["iOS", "Android"], [1, 1]),
    }
    BROWSER_WEIGHTED_POOLS: Dict[str, WeightedPool] = {
        "Windows": (["Chrome", "Firefox", "Opera", "Microsoft Edge", "Internet Explorer"], [12, 4, 2, 1, 1]),
        "Mac OS X": (["Chrome", "Firefox", "Opera", "Safari"], [4, 2, 1, 2]),
        "Linux": (["Chrome", "Firefox", "Opera"], [3, 3, 1]),
        "Chrome OS": (["Chrome"], [1]),
        "iOS": (["Mobile Safari", "Chrome iOS", "Firefox iOS"], [8, 1, 1]),
        "Android": (["Chrome", "Android Mobile", "Samsung Internet", "Firefox"], [5, 3, 3, 1]),
    }

    random: mimesis.random.Random

    def device_type_os_browser(self) -> Tuple[str, str, str]:
        device_type_pool, device_type_weights = self.DEVICE_TYPE_WEIGHTED_POOL
        device_type = self.random.choices(device_type_pool, device_type_weights)[0]
        os_pool, os_weights = self.OS_WEIGHTED_POOLS[device_type]
        os = self.random.choices(os_pool, os_weights)[0]
        browser_pool, browser_weights = self.BROWSER_WEIGHTED_POOLS[os]
        browser = self.random.choices(browser_pool, browser_weights)[0]
        return device_type, os, browser


class HoglifyDataGenerator(DataGenerator):
    """
        Hoglify is one of the leading providers of static hosting/serverless services.
        It caters to individual developers and teams of all sizes, but most of its revenue comes from large orgs.
    """

    properties_provider: PropertiesProvider
    person_provider: mimesis.Person
    numeric_provider: mimesis.Numeric
    address_provider: mimesis.Address
    internet_provider: mimesis.Internet
    datetime_provider: mimesis.Datetime

    def __init__(self, *, n_people: int = 1000, n_days: int = 90, seed: Optional[int] = None):
        super().__init__(n_people=n_people, n_days=n_days, seed=seed)
        self.properties_provider = PropertiesProvider(seed=seed)
        self.person_provider = mimesis.Person(seed=seed)
        self.numeric_provider = mimesis.Numeric(seed=seed)
        self.address_provider = mimesis.Address(seed=seed)
        self.internet_provider = mimesis.Internet(seed=seed)
        self.datetime_provider = mimesis.Datetime(seed=seed)

    def _set_project_up(self, team: Team, user: User):
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
            name="Signup page redesign",
            rollout_percentage=SIGNUP_PAGE_FLAG_ROLLOUT * 100,
            created_by=user,
        )

    def _create_person_with_journey(self, team: Team, user: User, index: int) -> SimPerson:
        now = dt.datetime.now()

        sim_person = SimPerson(team)

        ### CONSTANTS ###
        # How many days ago was this user first seen - this can be before the simulation period
        first_ever_session_days_ago = math.floor(
            self.properties_provider.random.betavariate(0.3, 1) * self.n_days / EXISTING_USERS_RATE
        )
        # How many days ago should the first simulated session be - this has to be withing the simulation period
        first_sim_session_days_ago = math.floor(
            min(self.n_days, first_ever_session_days_ago) * self.properties_provider.random.betavariate(1.2, 0.8)
        )
        # Device metadata
        device_type, os, browser = self.properties_provider.device_type_os_browser()
        ip = self.internet_provider.ip_v4()

        ### VARIABLES ###
        product_satisfaction = self.properties_provider.random.betavariate(2, 4)

        base_properties = {
            "$device_type": device_type,
            "$os": os,
            "$browser": browser,
            "$ip": ip,
            "$current_url": "https://posthog.com/",
            "$referrer": "https://www.google.com/",
            "$referring_domain": "www.google.com",
        }

        first_ever_session_date = now.date() - dt.timedelta(first_ever_session_days_ago)
        for days_ago in range(first_sim_session_days_ago, -1, -1):
            day_now = now - dt.timedelta(days_ago)
            sim_person.add_event("$pageview", day_now, base_properties)

        return sim_person


hoglify_data_generator = HoglifyDataGenerator()
