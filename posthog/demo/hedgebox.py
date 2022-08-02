from typing import Literal, Optional

from django.utils import timezone

from posthog.constants import INSIGHT_TRENDS, TRENDS_LINEAR, TRENDS_WORLD_MAP
from posthog.models import Cohort, Dashboard, DashboardTile, Experiment, FeatureFlag, Insight, InsightViewed
from posthog.models.utils import UUIDT

from .matrix.matrix import Cluster, Matrix
from .matrix.models import SimPerson

PROJECT_NAME = "Hedgebox"

# Event names
EVENT_SIGNED_UP = "signed_up"
EVENT_PAID_BILL = "paid_bill"
EVENT_DOWNLOADED_FILE = "downloaded_file"
EVENT_UPLOADED_FILE = "uploaded_file"
EVENT_DELETED_FILE = "deleted_file"
EVENT_COPIED_LINK = "copied_link"

# Group types
GROUP_TYPE_ORGANIZATION = "organization"

# Feature flags
FILE_PREVIEWS_FLAG_KEY = "file-previews"
NEW_SIGNUP_PAGE_FLAG_KEY = "signup-page-4.0"
NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT = 50
PROPERTY_NEW_SIGNUP_PAGE_FLAG = f"$feature/{NEW_SIGNUP_PAGE_FLAG_KEY}"
SIGNUP_SUCCESS_RATE_TEST = 0.5794
SIGNUP_SUCCESS_RATE_CONTROL = 0.4887

# How many clusters should be companies (made up of professional users) as opposed to social circles (personal users)
COMPANY_CLUSTERS_PROPORTION = 0.3


class HedgeboxPerson(SimPerson):
    cluster: "HedgeboxCluster"

    # Dynamic aspects
    _need: float  # 0 means no need, 1 means desperate
    _satisfaction: float  # -1 means hate, 0 means neutrality, 1 means love
    plan: Optional[Literal[0, 1, 2]]  # None means person has no account, 0 means free, 1 means 100 GB, 2 means 1 TB

    # Static aspects
    name: str
    email: str
    country_code: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.need = self.cluster.random.uniform(0.6 if self.kernel else 0, 1 if self.kernel else 0.3)
        self.satisfaction = 0.0
        self.plan = None
        self.name = self.cluster.person_provider.full_name()
        self.email = self.cluster.person_provider.email()
        self.country_code = (
            "US" if self.cluster.random.random() < 0.9132 else self.cluster.address_provider.country_code()
        )

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    @property
    def need(self) -> float:
        return self._need

    @need.setter
    def need(self, value):
        self._need = max(0, min(1, value))

    @property
    def satisfaction(self) -> float:
        return self._satisfaction

    @satisfaction.setter
    def satisfaction(self, value):
        self._satisfaction = max(-1, min(1, value))

    def _move_satisfaction(self, delta: float):
        self.satisfaction += delta

    def _move_need(self, delta: float):
        self.need += delta

    def _simulate_session(self):
        super()._simulate_session()
        # Make sure the time makes sense
        self._simulation_time += timezone.timedelta(
            seconds=self.cluster.random.betavariate(2.5, 1 + self.need) * (36_000 if self.plan is not None else 172_800)
            + 24
        )
        if not 5 < self._simulation_time.hour < 23 and self.cluster.random.random() < 0.9:
            return  # Not likely to be active at night
        if (
            self._simulation_time.weekday() < 5
            and 9 < self._simulation_time.hour < 17
            and self.cluster.random.random() < 0.5
        ):
            return  # Not very likely to be active during the work day

        self._active_client.start_session(
            str(UUIDT(int(self._simulation_time.timestamp()), seeded_random=self.cluster.random))
        )

        if (
            PROPERTY_NEW_SIGNUP_PAGE_FLAG not in self._super_properties
            and self._simulation_time >= self.cluster.matrix.new_signup_page_experiment_start
        ):
            self._register(
                {
                    PROPERTY_NEW_SIGNUP_PAGE_FLAG: "test"
                    if self.cluster.random.random() < (NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT / 100)
                    else "control"
                },
            )

        self._register({"$geoip_country_code": self.country_code})
        self._identify(None, {"$geoip_country_code": self.country_code})

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
        # More likely to finish signing up with the new signup page
        success_rate = (
            SIGNUP_SUCCESS_RATE_TEST
            if self._super_properties.get(PROPERTY_NEW_SIGNUP_PAGE_FLAG) == "test"
            else SIGNUP_SUCCESS_RATE_CONTROL
        )
        success = self.cluster.random.random() < success_rate  # What's the outlook?
        if success:  # Let's do this!
            self._capture(EVENT_SIGNED_UP, current_url="https://hedgebox.net/register/")
            self._advance_timer(self.cluster.random.uniform(0.1, 0.2))
            self._identify(self.email, {"email": self.email, "name": self.name})
            self._group_identify(GROUP_TYPE_ORGANIZATION, self.cluster.company_name or self.name)
            self.plan = 0
            self.satisfaction += (self.cluster.random.betavariate(1.5, 1.2) - 0.5) * 0.2
            self._capture_pageview("https://hedgebox.net/my_files/")
            self._consider_uploading_files()
        else:  # Something didn't go right...
            self.satisfaction += (self.cluster.random.betavariate(1, 3) - 0.75) * 0.5
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
        self.satisfaction += self.cluster.random.uniform(-0.19, 0.2)
        if self.satisfaction > 0.9:
            self._affect_neighbors(lambda other: other._move_need(0.05))

    def _consider_downloading_file(self):
        self._capture(EVENT_DOWNLOADED_FILE, current_url="https://hedgebox.net/my_files/")
        if self.satisfaction > 0.9:
            self._affect_neighbors(lambda other: other._move_need(0.05))

    def _consider_deleting_file(self):
        self._capture(EVENT_DELETED_FILE, current_url="https://hedgebox.net/my_files/")

    def _share_file_link(self):
        self._capture(EVENT_COPIED_LINK, current_url="https://hedgebox.net/my_files/")

    def _receive_file_link(self):
        file_name = self.cluster.file_provider.file_name()
        self._capture_pageview(f"https://hedgebox.net/my_files/{file_name}/")
        self._consider_downloading_file()


class HedgeboxCluster(Cluster):
    matrix: "HedgeboxMatrix"

    MIN_RADIUS: int = 1
    MAX_RADIUS: int = 6

    # None means the cluster is a social circle instead of a company
    company_name: Optional[str]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_company = self.random.random() < COMPANY_CLUSTERS_PROPORTION
        self.company_name = self.finance_provider.company() if is_company else None

    def __str__(self) -> str:
        return self.company_name or f"social circle {self.index+1}"

    def _radius_distribution(self) -> int:
        return int(self.MIN_RADIUS + self.random.betavariate(1.5, 5) * (self.MAX_RADIUS - self.MIN_RADIUS))

    def _initation_distribution(self) -> float:
        return self.random.betavariate(1.8, 1)


class HedgeboxMatrix(Matrix):
    person_model = HedgeboxPerson
    cluster_model = HedgeboxCluster

    new_signup_page_experiment_start: timezone.datetime
    new_signup_page_experiment_end: timezone.datetime

    def __init__(
        self,
        seed: Optional[str] = None,
        *,
        now: timezone.datetime,
        days_past: int = 120,
        days_future: int = 30,
        n_clusters: int,
    ):
        super().__init__(seed, now=now, days_past=days_past, days_future=days_future, n_clusters=n_clusters)
        # Start new signup page experiment roughly halfway through the simulation, end late into it
        self.new_signup_page_experiment_end = self.now - timezone.timedelta(days=2, hours=3, seconds=43)
        self.new_signup_page_experiment_start = self.start + (self.new_signup_page_experiment_end - self.start) / 2

    def set_project_up(self, team, user):
        super().set_project_up(team, user)
        team.name = PROJECT_NAME

        # Dashboard: Key metrics (project home)
        key_metrics_dashboard = Dashboard.objects.create(
            team=team, name="🔑 Key metrics", description="Company overview.", pinned=True
        )
        team.primary_dashboard = key_metrics_dashboard
        weekly_signups_insight = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Weekly signups",
            filters={
                "events": [{"id": EVENT_SIGNED_UP, "type": "events", "order": 0}],
                "actions": [],
                "display": TRENDS_LINEAR,
                "insight": INSIGHT_TRENDS,
                "interval": "week",
                "date_from": "-1m",
            },
            last_modified_at=timezone.now() - timezone.timedelta(days=23),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=weekly_signups_insight,
            color="blue",
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )
        signups_by_country_insight = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Last month's signups by country",
            filters={
                "events": [{"id": EVENT_SIGNED_UP, "type": "events", "order": 0}],
                "actions": [],
                "display": TRENDS_WORLD_MAP,
                "insight": INSIGHT_TRENDS,
                "breakdown_type": "event",
                "breakdown": "$geoip_country_code",
                "date_from": "-1m",
            },
            last_modified_at=timezone.now() - timezone.timedelta(days=6),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=signups_by_country_insight,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )
        signup_from_homepage_funnel = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Homepage view to signup conversion",
            filters={
                "events": [
                    {
                        "custom_name": "Viewed homepage",
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "https://hedgebox.net/",
                                "operator": "exact",
                            }
                        ],
                    },
                    {
                        "custom_name": "Viewed signup page",
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 1,
                        "properties": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "https:\\/\\/hedgebox\\.net\\/register($|\\/)",
                                "operator": "regex",
                            }
                        ],
                    },
                    {"custom_name": "Signed up", "id": "signed_up", "name": "signed_up", "type": "events", "order": 2},
                ],
                "actions": [],
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "funnel_viz_type": "steps",
                "filter_test_accounts": True,
                "date_from": "-1m",
            },
            last_modified_at=timezone.now() - timezone.timedelta(days=19),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=signup_from_homepage_funnel,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )
        weekly_uploader_retention = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Weekly uploader retention",
            filters={
                "period": "Week",
                "display": "ActionsTable",
                "insight": "RETENTION",
                "properties": [],
                "target_entity": {"id": "uploaded_file", "name": "uploaded_file", "type": "events", "order": 0},
                "retention_type": "retention_first_time",
                "total_intervals": 11,
                "returning_entity": {"id": "uploaded_file", "name": "uploaded_file", "type": "events", "order": 0},
                "filter_test_accounts": True,
            },
            last_modified_at=timezone.now() - timezone.timedelta(days=34),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=weekly_uploader_retention,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3, "moved": False, "static": False},
            },
        )

        # InsightViewed
        InsightViewed.objects.bulk_create(
            (
                InsightViewed(
                    team=team,
                    user=user,
                    insight=insight,
                    last_viewed_at=(
                        timezone.now()
                        - timezone.timedelta(days=self.random.randint(0, 3), minutes=self.random.randint(5, 60))
                    ),
                )
                for insight in Insight.objects.filter(team=team)
            )
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
            created_at=self.now - timezone.timedelta(days=15),
        )

        # Experiments
        new_signup_page_flag = FeatureFlag.objects.create(
            team=team,
            key=NEW_SIGNUP_PAGE_FLAG_KEY,
            name="New sign-up flow",
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                        {"key": "test", "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                    ]
                },
            },
            created_by=user,
            created_at=self.new_signup_page_experiment_start - timezone.timedelta(hours=1),
        )
        Experiment.objects.create(
            team=team,
            name="New sign-up flow",
            description="We've rebuilt our sign-up page to offer a more personalized experience. Let's see if this version performs better with potential users.",
            feature_flag=new_signup_page_flag,
            created_by=user,
            filters={
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "key": "$current_url",
                                "type": "event",
                                "value": "https:\\/\\/hedgebox\\.net\\/register($|\\/)",
                                "operator": "regex",
                            }
                        ],
                    },
                    {"id": "signed_up", "name": "signed_up", "type": "events", "order": 1},
                ],
                "actions": [],
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "funnel_viz_type": "steps",
                "filter_test_accounts": True,
            },
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                    {"key": "test", "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.43),
                "recommended_running_time": None,
                "minimum_detectable_effect": 1,
            },
            start_date=self.new_signup_page_experiment_start,
            end_date=self.new_signup_page_experiment_end,
            created_at=new_signup_page_flag.created_at,
        )
