import datetime as dt
from dataclasses import dataclass
from typing import Optional

from django.db import IntegrityError

from posthog.constants import (
    INSIGHT_TRENDS,
    PAGEVIEW_EVENT,
    RETENTION_FIRST_TIME,
    TRENDS_LINEAR,
    TRENDS_WORLD_MAP,
)
from posthog.demo.matrix.matrix import Cluster, Matrix
from posthog.demo.matrix.randomization import Industry
from posthog.models import (
    Action,
    Cohort,
    Dashboard,
    DashboardTile,
    Experiment,
    FeatureFlag,
    Insight,
    InsightViewed,
)

from .models import HedgeboxAccount, HedgeboxPerson
from .taxonomy import (
    COMPANY_CLUSTERS_PROPORTION,
    EVENT_SIGNED_UP,
    EVENT_UPLOADED_FILE,
    EVENT_DOWNLOADED_FILE,
    EVENT_DELETED_FILE,
    EVENT_SHARED_FILE_LINK,
    EVENT_UPGRADED_PLAN,
    EVENT_PAID_BILL,
    URL_HOME,
    URL_SIGNUP,
    FILE_PREVIEWS_FLAG_KEY,
    NEW_SIGNUP_PAGE_FLAG_KEY,
    NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT,
)


@dataclass
class HedgeboxCompany:
    name: str
    industry: Industry


class HedgeboxCluster(Cluster):
    matrix: "HedgeboxMatrix"

    MIN_RADIUS: int = 0
    MAX_RADIUS: int = 6

    # Properties
    company: Optional[HedgeboxCompany]  # None means the cluster is a social circle instead of a company

    # Internal state - plain
    _business_account: Optional[HedgeboxAccount]  # In social circle clusters the person-level account is used

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_company = self.random.random() < COMPANY_CLUSTERS_PROPORTION
        if is_company:
            self.company = HedgeboxCompany(
                name=self.finance_provider.company(),
                industry=self.properties_provider.industry(),
            )
        else:
            self.company = None
        self._business_account = None

    def __str__(self) -> str:
        return self.company.name if self.company else f"Social Circle #{self.index+1}"

    def radius_distribution(self) -> float:
        return self.random.betavariate(1.5, 5)

    def initiation_distribution(self) -> float:
        return self.random.betavariate(1.8, 1)


class HedgeboxMatrix(Matrix):
    PRODUCT_NAME = "Hedgebox"
    CLUSTER_CLASS = HedgeboxCluster
    PERSON_CLASS = HedgeboxPerson

    new_signup_page_experiment_start: dt.datetime
    new_signup_page_experiment_end: dt.datetime

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Start new signup page experiment roughly halfway through the simulation, end soon before `now`
        self.new_signup_page_experiment_end = self.now - dt.timedelta(days=2, hours=3, seconds=43)
        self.new_signup_page_experiment_start = self.start + (self.new_signup_page_experiment_end - self.start) / 2

    def set_project_up(self, team, user):
        super().set_project_up(team, user)

        # Actions
        interacted_with_file_action = Action.objects.create(
            name="Interacted with file",
            team=team,
            description="Logged-in interaction with a file.",
            created_by=user,
            steps_json=[
                {
                    "event": EVENT_UPLOADED_FILE,
                },
                {
                    "event": EVENT_DOWNLOADED_FILE,
                },
                {
                    "event": EVENT_DELETED_FILE,
                },
                {
                    "event": EVENT_SHARED_FILE_LINK,
                },
            ],
        )
        Action.objects.create(
            name="Visited Marius Tech Tips",
            team=team,
            description="Visited the best page for tech tips on the internet",
            created_by=user,
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "mariustechtips",
                    "url_matching": "regex",
                }
            ],
            pinned_at=self.now - dt.timedelta(days=3),
        )

        # Cohorts
        Cohort.objects.create(
            team=team,
            name="Signed-up users",
            created_by=user,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "is_set",
                            "operator": "is_set",
                        }
                    ]
                }
            ],
        )
        real_users_cohort = Cohort.objects.create(
            team=team,
            name="Real persons",
            description="People who don't belong to the Hedgebox team.",
            created_by=user,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@hedgebox.net$",
                            "operator": "not_regex",
                        }
                    ]
                }
            ],
        )
        team.test_account_filters = [{"key": "id", "type": "cohort", "value": real_users_cohort.pk}]

        # Dashboard: Key metrics (project home)
        key_metrics_dashboard = Dashboard.objects.create(
            team=team,
            name="🔑 Key metrics",
            description="Company overview.",
            pinned=True,
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
                "date_from": "-8w",
            },
            last_modified_at=self.now - dt.timedelta(days=23),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=weekly_signups_insight,
            color="blue",
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 0,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
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
            last_modified_at=self.now - dt.timedelta(days=6),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=signups_by_country_insight,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 5,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )
        activation_funnel = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Activation",
            filters={
                "events": [
                    {
                        "custom_name": "Signed up",
                        "id": EVENT_SIGNED_UP,
                        "name": EVENT_SIGNED_UP,
                        "type": "events",
                        "order": 2,
                    },
                    {
                        "custom_name": "Upgraded plan",
                        "id": EVENT_UPGRADED_PLAN,
                        "name": EVENT_UPGRADED_PLAN,
                        "type": "events",
                        "order": 4,
                    },
                ],
                "actions": [
                    {
                        "id": interacted_with_file_action.pk,
                        "name": interacted_with_file_action.name,
                        "type": "actions",
                        "order": 3,
                    }
                ],
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "funnel_viz_type": "steps",
                "filter_test_accounts": True,
                "date_from": "-1m",
            },
            last_modified_at=self.now - dt.timedelta(days=19),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=activation_funnel,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 10,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )
        new_user_retention = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="New user retention",
            filters={
                "period": "Week",
                "display": "ActionsTable",
                "insight": "RETENTION",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "is_set",
                                    "operator": "is_set",
                                }
                            ],
                        }
                    ],
                },
                "target_entity": {
                    "id": EVENT_SIGNED_UP,
                    "name": EVENT_SIGNED_UP,
                    "type": "events",
                    "order": 0,
                },
                "retention_type": RETENTION_FIRST_TIME,
                "total_intervals": 9,
                "returning_entity": {
                    "id": interacted_with_file_action.pk,
                    "name": interacted_with_file_action.name,
                    "type": "actions",
                    "order": 0,
                },
            },
            last_modified_at=self.now - dt.timedelta(days=34),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=new_user_retention,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 15,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )
        active_user_lifecycle = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Active user lifecycle",
            description="An active user being defined by interaction with files.",
            filters={
                "events": [],
                "actions": [
                    {
                        "id": interacted_with_file_action.pk,
                        "math": "total",
                        "name": interacted_with_file_action.name,
                        "type": "actions",
                        "order": 0,
                    }
                ],
                "compare": False,
                "display": "ActionsLineGraph",
                "insight": "LIFECYCLE",
                "interval": "day",
                "shown_as": "Lifecycle",
                "date_from": "-8w",
                "new_entity": [],
                "properties": [],
                "filter_test_accounts": True,
            },
            last_modified_at=self.now - dt.timedelta(days=34),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=active_user_lifecycle,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 10, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 20,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )
        weekly_file_volume = Insight.objects.create(
            team=team,
            dashboard=key_metrics_dashboard,
            saved=True,
            name="Weekly file volume",
            filters={
                "events": [
                    {
                        "custom_name": "Uploaded bytes",
                        "id": EVENT_UPLOADED_FILE,
                        "math": "sum",
                        "name": EVENT_UPLOADED_FILE,
                        "type": "events",
                        "order": 0,
                        "math_property": "file_size_b",
                    },
                    {
                        "custom_name": "Deleted bytes",
                        "id": EVENT_DELETED_FILE,
                        "math": "sum",
                        "name": EVENT_DELETED_FILE,
                        "type": "events",
                        "order": 1,
                        "math_property": "file_size_b",
                    },
                ],
                "actions": [],
                "display": "ActionsLineGraph",
                "insight": "TRENDS",
                "interval": "week",
                "date_from": "-8w",
                "new_entity": [],
                "properties": [],
                "filter_test_accounts": True,
            },
            last_modified_at=self.now - dt.timedelta(days=18),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=key_metrics_dashboard,
            insight=weekly_file_volume,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 10, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 25,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )

        # Dashboard: Revenue
        revenue_dashboard = Dashboard.objects.create(team=team, name="💸 Revenue", pinned=True)
        monthly_app_revenue_trends = Insight.objects.create(
            team=team,
            dashboard=revenue_dashboard,
            saved=True,
            name="Monthly app revenue",
            filters={
                "events": [
                    {
                        "id": EVENT_PAID_BILL,
                        "type": "events",
                        "order": 0,
                        "math": "sum",
                        "math_property": "amount_usd",
                    }
                ],
                "actions": [],
                "display": TRENDS_LINEAR,
                "insight": INSIGHT_TRENDS,
                "interval": "month",
                "date_from": "-6m",
            },
            last_modified_at=self.now - dt.timedelta(days=29),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=revenue_dashboard,
            insight=monthly_app_revenue_trends,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 0,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )
        bills_paid_trends = Insight.objects.create(
            team=team,
            dashboard=revenue_dashboard,
            saved=True,
            name="Bills paid",
            filters={
                "events": [
                    {
                        "id": EVENT_PAID_BILL,
                        "math": "unique_group",
                        "name": "paid_bill",
                        "type": "events",
                        "order": 0,
                        "math_group_type_index": 0,
                    }
                ],
                "actions": [],
                "compare": True,
                "date_to": None,
                "display": "BoldNumber",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
                "properties": [],
                "filter_test_accounts": True,
            },
            last_modified_at=self.now - dt.timedelta(days=29),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=revenue_dashboard,
            insight=bills_paid_trends,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 5,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )

        # Dashboard: Website
        website_dashboard = Dashboard.objects.create(team=team, name="🌐 Website")
        daily_unique_visitors_trends = Insight.objects.create(
            team=team,
            dashboard=website_dashboard,
            saved=True,
            name="Daily unique visitors over time",
            filters={
                "events": [{"id": PAGEVIEW_EVENT, "type": "events", "order": 0, "math": "dau"}],
                "actions": [],
                "display": TRENDS_LINEAR,
                "insight": INSIGHT_TRENDS,
                "interval": "day",
                "date_from": "-6m",
            },
            last_modified_at=self.now - dt.timedelta(days=29),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=website_dashboard,
            insight=daily_unique_visitors_trends,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 0,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )
        most_popular_pages_trends = Insight.objects.create(
            team=team,
            dashboard=website_dashboard,
            saved=True,
            name="Most popular pages",
            filters={
                "events": [
                    {
                        "id": PAGEVIEW_EVENT,
                        "math": "total",
                        "type": "events",
                        "order": 0,
                    }
                ],
                "actions": [],
                "display": "ActionsTable",
                "insight": "TRENDS",
                "interval": "day",
                "breakdown": "$current_url",
                "date_from": "-6m",
                "new_entity": [],
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$current_url",
                                    "type": "event",
                                    "value": "/files/",
                                    "operator": "not_icontains",
                                }
                            ],
                        }
                    ],
                },
                "breakdown_type": "event",
            },
            last_modified_at=self.now - dt.timedelta(days=26),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=website_dashboard,
            insight=most_popular_pages_trends,
            layouts={
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {
                    "h": 5,
                    "w": 1,
                    "x": 0,
                    "y": 5,
                    "minH": 5,
                    "minW": 3,
                    "moved": False,
                    "static": False,
                },
            },
        )

        # Insight
        Insight.objects.create(
            team=team,
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
                                "value": URL_HOME,
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
                                "value": URL_SIGNUP,
                                "operator": "regex",
                            }
                        ],
                    },
                    {
                        "custom_name": "Signed up",
                        "id": "signed_up",
                        "name": "signed_up",
                        "type": "events",
                        "order": 2,
                    },
                ],
                "actions": [],
                "display": "FunnelViz",
                "insight": "FUNNELS",
                "interval": "day",
                "funnel_viz_type": "steps",
                "filter_test_accounts": True,
                "date_from": "-1m",
            },
            last_modified_at=self.now - dt.timedelta(days=19),
            last_modified_by=user,
        )
        Insight.objects.create(
            team=team,
            saved=True,
            name="User paths starting at homepage",
            filters={
                "date_to": None,
                "insight": "PATHS",
                "date_from": "-30d",
                "edge_limit": 50,
                "properties": {"type": "AND", "values": []},
                "step_limit": 5,
                "start_point": URL_HOME,
                "funnel_filter": {},
                "exclude_events": [],
                "path_groupings": ["/files/*"],
                "include_event_types": ["$pageview"],
                "local_path_cleaning_filters": [],
            },
            last_modified_at=self.now - dt.timedelta(days=9),
            last_modified_by=user,
        )
        Insight.objects.create(
            team=team,
            saved=True,
            name="File interactions",
            filters={
                "events": [
                    {"id": EVENT_UPLOADED_FILE, "type": "events", "order": 0},
                    {"id": EVENT_DELETED_FILE, "type": "events", "order": 2},
                    {"id": EVENT_DOWNLOADED_FILE, "type": "events", "order": 1},
                ],
                "actions": [],
                "display": TRENDS_LINEAR,
                "insight": INSIGHT_TRENDS,
                "interval": "day",
                "date_from": "-30d",
            },
            last_modified_at=self.now - dt.timedelta(days=13),
            last_modified_by=user,
        )

        # InsightViewed
        try:
            InsightViewed.objects.bulk_create(
                (
                    InsightViewed(
                        team=team,
                        user=user,
                        insight=insight,
                        last_viewed_at=(
                            self.now
                            - dt.timedelta(
                                days=self.random.randint(0, 3),
                                minutes=self.random.randint(5, 60),
                            )
                        ),
                    )
                    for insight in Insight.objects.filter(team=team)
                ),
            )
        except IntegrityError:
            pass  # This can happen if demo data generation is re-run for the same project

        # Feature flags
        try:
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
                created_at=self.now - dt.timedelta(days=15),
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
                            {
                                "key": "control",
                                "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT,
                            },
                            {
                                "key": "test",
                                "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT,
                            },
                        ]
                    },
                },
                created_by=user,
                created_at=self.new_signup_page_experiment_start - dt.timedelta(hours=1),
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
                                    "value": URL_SIGNUP,
                                    "operator": "exact",
                                }
                            ],
                        },
                        {
                            "id": "signed_up",
                            "name": "signed_up",
                            "type": "events",
                            "order": 1,
                        },
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
                        {
                            "key": "control",
                            "rollout_percentage": 100 - NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT,
                        },
                        {
                            "key": "test",
                            "rollout_percentage": NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT,
                        },
                    ],
                    "recommended_sample_size": int(len(self.clusters) * 0.274),
                    "recommended_running_time": None,
                    "minimum_detectable_effect": 1,
                },
                start_date=self.new_signup_page_experiment_start,
                end_date=self.new_signup_page_experiment_end,
                created_at=new_signup_page_flag.created_at,
            )
        except IntegrityError:
            pass  # This can happen if demo data generation is re-run for the same project
