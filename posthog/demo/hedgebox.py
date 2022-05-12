import datetime as dt
from typing import Literal, Optional

from posthog.constants import INSIGHT_FUNNELS, INSIGHT_TRENDS, TRENDS_FUNNEL, TRENDS_LINEAR, TRENDS_WORLD_MAP
from posthog.models import Cohort, Dashboard, Experiment, FeatureFlag, Insight
from posthog.models.property_definition import PropertyType
from posthog.models.utils import UUIDT

from .matrix.matrix import Cluster, Matrix
from .matrix.models import EVENT_GROUP_IDENTIFY, EVENT_IDENTIFY, EVENT_PAGELEAVE, EVENT_PAGEVIEW, SimPerson

PROJECT_NAME = "Hedgebox"

# Event name constants
EVENT_SIGNED_UP = "signed_up"
EVENT_PAID_BILL = "paid_bill"
EVENT_DOWNLOADED_FILE = "downloaded_file"
EVENT_UPLOADED_FILE = "uploaded_file"
EVENT_DELETED_FILE = "deleted_file"
EVENT_COPIED_LINK = "copied_link"

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
        self.need = self.cluster.random.uniform(0.6 if self.kernel else 0, 1 if self.kernel else 0.3)
        self.satisfaction = 0.0
        self.usage_profile = self.cluster.random.betavariate(1, 2)  # Most users skew personal
        self.plan = None
        self.name = self.cluster.person_provider.full_name()
        self.email = self.cluster.person_provider.email()

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def _simulate_session(self):
        super()._simulate_session()
        # Make sure the time makes sense
        self._simulation_time += dt.timedelta(seconds=self.cluster.random.betavariate(2.5, 1 + self.need) * 36_000 + 24)
        if self._simulation_time >= self.cluster.end:
            return
        if not 5 < self._simulation_time.hour < 23 and self.cluster.random.random() < 0.9:
            return
        if 9 < self._simulation_time.hour < 17 and self.cluster.random.random() < 0.7:
            return
        self._active_client.start_session(
            str(UUIDT(int(self._simulation_time.timestamp()), seeded_random=self.cluster.random))
        )
        if self.need >= 0.3:
            if self.plan is None:
                self._visit_homepage()
                if self.satisfaction > 0:
                    self._consider_signing_up()
            else:
                if self.cluster.random.random() < 0.2:
                    self._visit_homepage()
                else:
                    self._capture_pageview("https://hedgebox.net/my_files/")
                    if self.cluster.random.random() < 0.5:
                        self._consider_uploading_files()
                    elif self.cluster.random.random() < 0.5:
                        self._consider_downloading_file()

    # Individual flows

    def _visit_homepage(self):
        self._capture_pageview("https://hedgebox.net/")
        self._advance_timer(0.5 + self.cluster.random.betavariate(1.1, 1.5) * 80)  # Viewing the page
        self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.2) * 0.15  # It's a nice page

    def _consider_signing_up(self):
        """Go through sign-up flow and return True if the user signed up."""
        self._capture_pageview("https://hedgebox.net/register/")  # Visiting the sign-up page
        self._advance_timer(15 + self.cluster.random.betavariate(1.1, 2) * 70)  # Looking at things, filling out forms
        success = self.cluster.random.random() < 0.7394  # What's the outlook?
        if success:  # Let's do this!
            self._capture(EVENT_SIGNED_UP, current_url="https://hedgebox.net/register/")
            self._advance_timer(self.cluster.random.uniform(0.1, 0.2))
            self._identify(self.email)
            self.plan = 0
            self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.5) * 0.2
            self._capture_pageview("https://hedgebox.net/my_files/")
            self._consider_uploading_files()
        else:  # Something didn't go right...
            self.satisfaction += (self.cluster.random.betavariate(1, 3) - 0.5) * 0.2
        return success

    def _consider_uploading_files(self):
        self._advance_timer(self.cluster.random.betavariate(2.5, 1.1) * 95)
        file_count = self.cluster.random.randint(1, 13)
        self.cluster.file_provider.extension()
        for _ in range(file_count):
            self._capture(
                EVENT_UPLOADED_FILE,
                current_url="https://hedgebox.net/my_files/",
                properties={"file_extension": self.cluster.file_provider.extension(),},
            )
        self.satisfaction += self.cluster.random.uniform(-0.05, 0.2)
        if self.satisfaction > 0.5:
            self._affect_neighbors(lambda other: other._move_need(0.5))

    def _consider_downloading_file(self):
        self._capture(EVENT_DOWNLOADED_FILE, current_url="https://hedgebox.net/my_files/")
        if self.satisfaction > 0.5:
            self._affect_neighbors(lambda other: other._move_need(0.5))

    def _consider_deleting_file(self):
        self._capture(EVENT_DELETED_FILE, current_url="https://hedgebox.net/my_files/")

    def _share_file_link(self):
        self._capture(EVENT_COPIED_LINK, current_url="https://hedgebox.net/my_files/")

    def _receive_file_link(self):
        file_name = self.cluster.file_provider.file_name()
        self._capture_pageview(f"https://hedgebox.net/my_files/{file_name}/")
        self._consider_downloading_file()

    def _upgrade_plan(self):
        pass
        # TODO

    def _downgrade_plan(self):
        pass
        # TODO

    def _recommend_product(self):
        pass
        # TODO

    def _move_satisfaction(self, delta: float):
        self.satisfaction = max(-1, min(1, self.satisfaction + delta))

    def _move_need(self, delta: float):
        self.need = max(0, min(1, self.need + delta))


class HedgeboxCluster(Cluster):
    MIN_RADIUS: int = 1
    MAX_RADIUS: int = 6

    company_name: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.company_name = self.finance_provider.company()

    def __str__(self) -> str:
        return self.company_name

    def _radius_distribution(self) -> int:
        return int(self.MIN_RADIUS + self.random.betavariate(1.5, 5) * (self.MAX_RADIUS - self.MIN_RADIUS))


class HedgeboxMatrix(Matrix):
    person_model = HedgeboxPerson
    cluster_model = HedgeboxCluster

    event_definitions = [
        EVENT_PAGEVIEW,
        EVENT_PAGELEAVE,
        EVENT_IDENTIFY,
        EVENT_GROUP_IDENTIFY,
        EVENT_SIGNED_UP,
        EVENT_PAID_BILL,
        EVENT_UPLOADED_FILE,
        EVENT_DELETED_FILE,
    ]
    property_definitions = [
        ("$distinct_id", None),
        ("$set", None),
        ("$set_once", None),
        ("$group_type", None),
        ("$group_key", None),
        ("$group_set", None),
        ("$lib", PropertyType.String),
        ("$device_type", PropertyType.String),
        ("$os", PropertyType.String),
        ("$browser", PropertyType.String),
        ("$session_id", PropertyType.String),
        ("$browser_id", PropertyType.String),
        ("$current_url", PropertyType.String),
        ("$host", PropertyType.String),
        ("$pathname", PropertyType.String),
        ("$referrer", PropertyType.String),
        ("$referring_domain", PropertyType.String),
        ("$timestamp", PropertyType.Datetime),
        ("email", PropertyType.String),
    ]

    def set_project_up(self, team, user):
        super().set_project_up(team, user)
        team.name = PROJECT_NAME

        # Dashboards
        key_metrics_dashboard = Dashboard.objects.create(
            team=team, name="🔑 Key metrics", description="Company overview.", pinned=True
        )
        team.primary_dashboard = key_metrics_dashboard

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
                "filter_test_accounts": True,
            },
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                    {"key": "test", "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                ],
                "recommended_sample_size": 1274,
                "recommended_running_time": None,
                "minimum_detectable_effect": 1,
            },
            start_date=self.start + dt.timedelta(seconds=self.random.uniform(90, 18_000)),
            created_at=self.start,  # FIXME
        )
