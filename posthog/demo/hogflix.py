import datetime as dt
import math
from typing import Dict, List, Optional, Tuple

import mimesis
import mimesis.random

from posthog.demo.data_generator import DataGenerator, SimPerson
from posthog.models import Dashboard, FeatureFlag, Insight, Team, User

try:
    from ee.models.event_definition import EnterpriseEventDefinition
    from ee.models.property_definition import EnterprisePropertyDefinition
except ImportError:
    pass

ORGANIZATION_NAME = "Hogflix Inc."
TEAM_NAME = "Hogflix"

SIGNUP_PAGE_FLAG_KEY = "signup-page-4.0"
SIGNUP_PAGE_FLAG_ROLLOUT = 0.5

# Rate determining how many out of all simulated users should be considered existing prior to the beginning of the sim
EXISTING_USERS_RATE = 0.7
# How many users are unemployed - meaning they have time to watch during the day
UNEMPLOYMENT_RATE = 0.05

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

    random: mimesis.random.Random

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

    def __init__(self, *, n_people: int = 1000, n_days: int = 90, seed: Optional[int] = None):
        super().__init__(n_people=n_people, n_days=n_days, seed=seed)
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

        # Constants
        # How eager is this user to watch flix in general
        eagerness = self.properties_provider.random.random()
        # How many days ago was this user first seen - this can be before the simulation period
        first_ever_session_days_ago = math.floor(
            self.properties_provider.random.betavariate(0.3, 1) * self.n_days / EXISTING_USERS_RATE
        )
        # How many days ago should the first simulated session be - this has to be withing the simulation period
        first_sim_session_days_ago = math.floor(
            min(self.n_days, first_ever_session_days_ago)
            * self.properties_provider.random.betavariate(1.2, 1 - eagerness / 2)
        )
        # Whether the user already is registered
        was_registered_before_sim = first_ever_session_days_ago > self.n_days
        # Unemployed users have more time for watching
        is_unemployed = self.properties_provider.random.random() < UNEMPLOYMENT_RATE
        # Whether the signup page 4.0 flag is enabled
        is_on_signup_page_flag = self.properties_provider.random.random() < SIGNUP_PAGE_FLAG_ROLLOUT
        # When does this user watch most commonly
        if is_unemployed:
            primary_time_of_day = self.properties_provider.random.choices(
                ["morning", "afternoon", "evening", "night"], weights=[2, 2, 3, 2]
            )[0]
        else:
            primary_time_of_day = self.properties_provider.random.choices(
                ["afternoon", "evening", "night"], weights=[2, 3, 1]
            )[0]
        # Favorite genres
        favorite_genres = self.properties_provider.random.choices(
            ["nature", "action", "romance", "comedy", "thriller", "drama", "fantasy", "musical", "animated"],
            weights=[10, 6, 4, 5, 4, 5, 4, 2, 2],
            k=3,
        )
        # Device metadata
        device_type, os, browser = self.properties_provider.device_type_os_browser()

        # Variables
        churn_risk = self.properties_provider.random.betavariate(2, 4)

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

        first_ever_session_date = now.date() - dt.timedelta(first_ever_session_days_ago)
        print(
            "xxxx",
            eagerness,
            first_ever_session_days_ago,
            first_sim_session_days_ago,
            was_registered_before_sim,
            is_unemployed,
            is_on_signup_page_flag,
            primary_time_of_day,
            favorite_genres,
            device_type,
            os,
            browser,
            churn_risk,
            first_ever_session_date,
        )
        for days_ago in range(first_sim_session_days_ago, 0, -1):
            day_now = now - dt.timedelta(days_ago)
            if self.properties_provider.random.random() < eagerness:
                sim_person.add_event("$pageview", day_now, base_properties)

        # Ideas:
        # - Recent show "Cash Theft" was a big hit with a record number of views and an increase in subscribers
        # - Users who started on macOS convert better
        # - Conversion is higher for users who wen through the new signup page
        # - The rate of growth is increasing
        # - "Nature" is the most popular genre

        return sim_person


hogflix_data_generator = HogflixDataGenerator(n_people=1)
