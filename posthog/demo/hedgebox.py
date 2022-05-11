import datetime as dt
from typing import Literal, Optional

from posthog.constants import INSIGHT_FUNNELS, INSIGHT_TRENDS, TRENDS_FUNNEL, TRENDS_LINEAR, TRENDS_WORLD_MAP
from posthog.models import Cohort, Dashboard, EventDefinition, Experiment, FeatureFlag, Insight, PropertyDefinition
from posthog.models.property_definition import PropertyType
from posthog.models.utils import UUIDT

from .matrix.matrix import Cluster, Matrix
from .matrix.models import EVENT_GROUP_IDENTIFY, EVENT_IDENTIFY, EVENT_PAGELEAVE, EVENT_PAGEVIEW, SimPerson

PROJECT_NAME = "Hedgebox"

# Event name constants
EVENT_SIGNED_UP = "signed_up"
EVENT_PAID_BILL = "paid_bill"

# Feature flag constants
FILE_PREVIEWS_FLAG_KEY = "file-previews"
NEW_SIGNUP_PAGE_FLAG_KEY = "signup-page-4.0"
NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT = 30


class HedgeboxPerson(SimPerson):
    need: float  # 0 means no need, 1 means desperate
    satisfaction: float  # -1 means hate, 0 means neutrality, 1 means love
    usage_profile: float  # 0 means fully personal use intentions, 1 means fully professional
    plan: Optional[Literal[0, 1, 2]]  # None means person has no account, 0 means free, 1 means 100 GB, 2 means 1 TB

    name: str
    email: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.need = self.cluster.random.uniform(0.7 if self.kernel else 0, 1 if self.kernel else 0.08)
        self.satisfaction = 0.0
        self.usage_profile = self.cluster.random.betavariate(1, 2)  # Most users skew personal
        self.plan = None
        self.name = self.cluster.person_provider.full_name()
        self.email = self.cluster.person_provider.email()

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def _simulate_session(self):
        self.active_client.start_session(
            str(UUIDT(int(self.simulation_time.timestamp()), seeded_random=self.cluster.random))
        )
        if self.plan is None and self.need > 0.5:
            capture_pageleave = self._capture_pageview("https://hedgebox.net/")  # Homepage!
            self._advance_timer(0.5 + self.cluster.random.betavariate(1.1, 1.5) * 80)  # Viewing the page
            self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.2) * 0.15  # It's a nice page
            if self.satisfaction > 0:
                capture_pageleave()
                self._consider_signing_up()
        self.simulation_time += dt.timedelta(days=365 * 100)

    # Individual flows

    def _consider_signing_up(self):
        """Go through sign-up flow and return True if the user signed up."""
        capture_pageleave = self._capture_pageview("https://hedgebox.net/register/")  # Visiting the sign-up page
        self._advance_timer(15 + self.cluster.random.betavariate(1.1, 2) * 70)  # Looking at things, filling out forms
        success = self.cluster.random.random() < 0.7  # What's the outlook?
        if success:  # Let's do this!
            self._capture(EVENT_SIGNED_UP, current_url="https://hedgebox.net/register/")
            self._advance_timer(self.cluster.random.uniform(0.1, 0.2))
            self._identify(self.email)
            self.has_signed_up = 0
            self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.5) * 0.2
        else:  # Something didn't go right...
            self.satisfaction += (self.cluster.random.betavariate(1, 3) - 0.5) * 0.2
        capture_pageleave()
        return success

    def _consider_uploading_files(self):
        pass

    def _consider_downloading_files(self):
        pass

    def _share_file_link(self):
        pass

    def _receive_file_link(self):
        pass

    def _upgrade_plan(self):
        pass

    def _downgrade_plan(self):
        pass

    def _recommend_product(self):
        pass


class HedgeboxCluster(Cluster):
    MIN_RADIUS: int = 1
    MAX_RADIUS: int = 6

    company_name: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.company_name = self.finance_provider.company()

    def __str__(self) -> str:
        return self.company_name

    def radius_distribution(self) -> int:
        return int(self.MIN_RADIUS + self.random.betavariate(1.5, 5) * (self.MAX_RADIUS - self.MIN_RADIUS))


class HedgeboxMatrix(Matrix):
    person_model = HedgeboxPerson
    cluster_model = HedgeboxCluster

    def set_project_up(self, team, user):
        team.name = PROJECT_NAME

        # Event definitions: built-ins
        EventDefinition.objects.create(team=team, name=EVENT_PAGEVIEW)
        EventDefinition.objects.create(team=team, name=EVENT_PAGELEAVE)
        EventDefinition.objects.create(team=team, name=EVENT_IDENTIFY)
        EventDefinition.objects.create(team=team, name=EVENT_GROUP_IDENTIFY)

        # Property definitions: built-ins
        PropertyDefinition.objects.create(team=team, name="$distinct_id")
        PropertyDefinition.objects.create(team=team, name="$set")
        PropertyDefinition.objects.create(team=team, name="$set_once")
        PropertyDefinition.objects.create(team=team, name="$group_type")
        PropertyDefinition.objects.create(team=team, name="$group_key")
        PropertyDefinition.objects.create(team=team, name="$group_set")
        PropertyDefinition.objects.create(team=team, name="$lib", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$device_type", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$os", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$browser", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$session_id", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$browser_id", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$current_url", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$host", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$pathname", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$referrer", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$referring_domain", property_type=PropertyType.String)
        PropertyDefinition.objects.create(team=team, name="$timestamp", property_type=PropertyType.Datetime)

        # Property definitions: custom
        PropertyDefinition.objects.create(team=team, name="email", property_type=PropertyType.String)

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
                "events": [{"id": EVENT_SIGNED_UP, "type": "events", "order": 0}],
                "actions": [],
                "display": TRENDS_LINEAR,
                "insight": INSIGHT_TRENDS,
                "interval": "week",
            },
        )
        Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            order=0,
            saved=True,
            name="Last month's signups by country",
            filters={
                "events": [{"id": EVENT_SIGNED_UP, "type": "events", "order": 0, "math": "dau"}],
                "actions": [],
                "display": TRENDS_WORLD_MAP,
                "insight": INSIGHT_TRENDS,
            },
        )

        # Cohorts
        Cohort.objects.create(
            team=team,
            name="Signed-up users",
            created_by=user,
            groups=[{"properties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}]}],
        )
        real_users_cohort = Cohort.objects.create(
            team=team,
            name="Real users",
            description="People who don't belong to the Hedgebox team.",
            created_by=user,
            groups=[
                {"properties": [{"key": "email", "type": "person", "value": "@hedgebox.net$", "operator": "not_regex"}]}
            ],
        )
        team.test_account_filters = [{"key": "id", "type": "cohort", "value": real_users_cohort.pk}]

        # Feature flags
        new_signup_page_flag = FeatureFlag.objects.create(
            team=team,
            key=FILE_PREVIEWS_FLAG_KEY,
            name="File previews (ticket #2137). Work-in-progress, so only visible internally at the moment",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": [
                                    "mark.s@hedgebox.net",
                                    "helly.r@hedgebox.net",
                                    "irving.b@hedgebox.net",
                                    "dylan.g@hedgebox.net",
                                ],
                                "operator": "exact",
                            }
                        ]
                    }
                ]
            },
            created_by=user,
            # TODO: created_at
        )

        # Experiments
        new_signup_page_flag = FeatureFlag.objects.create(
            team=team,
            key=NEW_SIGNUP_PAGE_FLAG_KEY,
            name="New sign-up flow",
            filters={"groups": [{"properties": [], "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT}]},
            created_by=user,
            # TODO: created_at
        )
        Experiment.objects.create(
            team=team,
            name="New sign-up flow",
            description="We've rebuilt our sign-up page to offer a more personalized experience. Let's see if this version performs better with potential users.",
            feature_flag=new_signup_page_flag,
            created_by=user,
            filters={
                "events": [
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 1},
                ],
                "actions": [],
                "date_from": "1970-01-01T00:00",
                "date_to": "1971-01-01T00:00",
                "display": TRENDS_FUNNEL,
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "funnel_viz_type": "steps",
                "filter_test_accounts": False,
            },
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                    {"key": "test", "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                ],
                "recommended_sample_size": 1274,
                "recommended_running_time": None,
                "minimum_detectable_effect": 1,
            }
            # TODO: created_at
            # TODO: start_date
        )
