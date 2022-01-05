import datetime as dt
import random
from typing import Dict, List, Optional, Tuple, cast

import mimesis
from rest_framework.request import Request

from posthog.demo.data_generator import DataGenerator, SimPerson
from posthog.models import Dashboard, FeatureFlag, Insight, Team, User
from posthog.utils import render_template

try:
    from ee.models.event_definition import EnterpriseEventDefinition
    from ee.models.property_definition import EnterprisePropertyDefinition
except ImportError:
    pass

ORGANIZATION_NAME = "Hogflix Inc."
TEAM_NAME = "Hogflix"

FEATURE_FLAG_KEY = "signup-page-4.0"

EVENT_SIGNUP_ENTERED = "signup_entered"
EVENT_SIGNUP_COMPLETED = "signup_completed"
EVENT_SUBSCRIPTION_PAID = "subscription_paid"
EVENT_SUBSCRIPTION_CANCELED = "subscription_canceled"
EVENT_WATCHING_STARTED = "watching_started"
EVENT_WATCHING_COMPLETED = "watching_completed"
EVENT_WATCHING_STOPPED = "watching_stopped"
EVENT_NPS_SURVEY = "nps_survey"

PROPERTY_PLAN = "plan"
PROPERTY_AMOUNT_USD = "amount_usd"
PROPERTY_COLLECTION_TYPE = "collection_type"
PROPERTY_COLLECTION_GENRE = "collection_genre"
PROPERTY_COLLECTION_TITLE = "collection_title"
PROPERTY_COLLECTION_ID = "collection_id"
PROPERTY_ENTRY_TYPE = "entry_type"
PROPERTY_ENTRY_TITLE = "entry_title"
PROPERTY_ENTRY_ID = "entry_id"
PROPERTY_SEASON = "season"
PROPERTY_EPISODE = "episode"
PROPERTY_NPS_RATING = "nps_rating"

WeightedPool = Tuple[List[str], List[int]]


class PropertiesProvider(mimesis.BaseProvider):
    DEVICE_TYPE_WEIGHTED_POOL: WeightedPool = (["Desktop", "Mobile", "Tablet"], [5, 3, 1])
    OS_WEIGHTED_POOLS: Dict[str, WeightedPool] = {
        "Desktop": (["Windows", "Mac OS X", "Linux", "Chrome OS"], [6, 3, 1, 1]),
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

    random: random.Random

    def device_type_os_browser(self) -> Tuple[str, str, str]:
        device_type_pool, device_type_weights = self.DEVICE_TYPE_WEIGHTED_POOL
        device_type = self.random.choices(device_type_pool, weights=device_type_weights)[0]
        os_pool, os_weights = self.OS_WEIGHTED_POOLS[device_type]
        os = self.random.choices(os_pool, os_weights)[0]
        browser_pool, browser_weights = self.BROWSER_WEIGHTED_POOLS[os]
        browser = self.random.choices(browser_pool, weights=browser_weights)[0]
        return device_type, os, browser


class HogflixDataGenerator(DataGenerator):
    properties_provider: PropertiesProvider
    person_provider: mimesis.Person
    numeric_provider: mimesis.Numeric
    address_provider: mimesis.Address
    datetime_provider: mimesis.Datetime

    def __init__(self, *, n_people: int = 1000, seed: Optional[int] = None):
        super().__init__(n_people=n_people, seed=seed)
        self.properties_provider = PropertiesProvider(seed=seed)
        self.person_provider = mimesis.Person(seed=seed)
        self.numeric_provider = mimesis.Numeric(seed=seed)
        self.address_provider = mimesis.Address(seed=seed)
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
        ## Watching
        EnterpriseEventDefinition.objects.create(
            team=team, name=EVENT_WATCHING_STARTED, description="Viewer started watching media"
        )
        EnterpriseEventDefinition.objects.create(
            team=team, name=EVENT_WATCHING_COMPLETED, description="Viewer reached credits"
        )
        EnterpriseEventDefinition.objects.create(
            team=team, name=EVENT_WATCHING_STOPPED, description="Viewed stopped watching"
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_COLLECTION_TYPE, description="Collection type: movie or show"
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_COLLECTION_GENRE, description="Collection genre"
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_COLLECTION_TITLE, description="Collection title"
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_COLLECTION_ID, description="Collection ID", is_numerical=True
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_ENTRY_TYPE, description="Entry type: movie or episode or trailer"
        )
        EnterprisePropertyDefinition.objects.create(team=team, name=PROPERTY_ENTRY_TITLE, description="Entry title")
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_ENTRY_ID, description="Entry ID", is_numerical=True
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_SEASON, description="Only for shows", is_numerical=True
        )
        EnterprisePropertyDefinition.objects.create(
            team=team, name=PROPERTY_EPISODE, description="Only for shows", is_numerical=True
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
            name="Daily views",
            filters={
                "events": [{"id": "watching_completed", "name": "watching_completed", "type": "events", "order": 0}],
                "actions": [],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "day",
            },
        )

        # TODO:
        # Popularity by genre
        # Revenue
        # New subscribers per day
        # Lifecycle
        # Monthly stickiness
        # Paths
        # Time from signup to first movie
        # Rate of trial to paid conversions per month
        # Paid user funnel
        # Rate of subscriptions started vs canceled

        # Ideas:
        # - Recent show "Cash Theft" was a big hit with a record number of views and an increase in subscribers
        # - Users who started on macOS convert better
        # - Conversion is higher for users who wen through the new signup page
        # - The rate of growth is increasing
        # - "Nature" is the most popular genre

        # Feature flags
        FeatureFlag.objects.create(
            team=team, key=FEATURE_FLAG_KEY, name="Signup page redesign", rollout_percentage=50, created_by=user
        )

    def _create_person_with_journey(self, team: Team, user: User, index: int) -> SimPerson:
        now = dt.datetime.now()
        journey_start = now - dt.timedelta(self.person_provider.random.randint(0, 90))
        device_type, os, browser = self.properties_provider.device_type_os_browser()

        base_properties = {
            "$device_type": device_type,
            "$os": os,
            "$browser": browser,
            "$initial_os": os,
            "$geoip_latitude": self.address_provider.latitude(),
            "$geoip_city_name": self.address_provider.city(),
            "$geoip_longitude": self.address_provider.longitude(),
            "$geoip_time_zone": self.datetime_provider.timezone(),
            "$geoip_postal_code": self.address_provider.zip_code(),
            "$geoip_country_code": self.address_provider.country_code(),
            "$geoip_country_name": self.address_provider.country(),
            "$geoip_continent_code": self.address_provider.continent(code=True),
            "$geoip_continent_name": self.address_provider.continent(),
            "$current_url": "https://posthog.com/",
            "$referrer": "https://www.google.com/",
            "$referring_domain": "www.google.com",
        }

        sim_person = SimPerson(team)

        # TODO: Build out simulation
        if self.person_provider.random.random() < 0.5:
            sim_person.add_event("$pageview", base_properties, journey_start)

        # TODO: Use session recording

        return sim_person


hogflix_data_generator = HogflixDataGenerator(n_people=1)


def demo_route(request: Request):
    user = cast(User, request.user)
    organization = user.organization

    if not organization:
        raise AttributeError("This user has no organization.")

    try:
        team = organization.teams.get(is_demo=True)
    except Team.DoesNotExist:
        team = hogflix_data_generator.create_team(organization, user)

    user.current_team = team
    user.save()
    return render_template("demo.html", request=request, context={"api_token": team.api_token})
