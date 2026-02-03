import csv
import uuid
import datetime as dt
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EntityType,
    EventPropertyFilter,
    EventsNode,
    FunnelsFilter,
    FunnelsQuery,
    FunnelVizType,
    InsightVizNode,
    IntervalType,
    LifecycleFilter,
    LifecycleQuery,
    PathsFilter,
    PathsQuery,
    PathType,
    PersonPropertyFilter,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    RetentionEntity,
    RetentionFilter,
    RetentionPeriod,
    RetentionQuery,
    RetentionType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.clickhouse.client import query_with_columns
from posthog.constants import PAGEVIEW_EVENT
from posthog.demo.matrix.matrix import Cluster, Matrix
from posthog.demo.matrix.randomization import Industry
from posthog.exceptions_capture import capture_exception
from posthog.models import (
    Action,
    Cohort,
    Dashboard,
    DashboardTile,
    Experiment,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
    FeatureFlag,
    Insight,
    InsightViewed,
)
from posthog.models.event_definition import EventDefinition
from posthog.models.oauth import OAuthApplication
from posthog.models.property_definition import PropertyType
from posthog.models.schema import EventSchema, SchemaPropertyGroup, SchemaPropertyGroupProperty
from posthog.storage import object_storage

from products.data_warehouse.backend.models.credential import get_or_create_datawarehouse_credential
from products.data_warehouse.backend.models.table import DataWarehouseTable

from .models import HedgeboxAccount, HedgeboxPerson
from .taxonomy import (
    COMPANY_CLUSTERS_PROPORTION,
    EVENT_DELETED_FILE,
    EVENT_DOWNLOADED_FILE,
    EVENT_PAID_BILL,
    EVENT_SHARED_FILE_LINK,
    EVENT_SIGNED_UP,
    EVENT_UPGRADED_PLAN,
    EVENT_UPLOADED_FILE,
    FILE_ENGAGEMENT_FLAG_KEY,
    FILE_PREVIEWS_FLAG_KEY,
    ONBOARDING_EXPERIMENT_FLAG_KEY,
    URL_HOME,
    URL_SIGNUP,
)

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User


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
        return self.company.name if self.company else f"Social Circle #{self.index + 1}"

    def radius_distribution(self) -> float:
        return self.random.betavariate(1.5, 5)

    def initiation_distribution(self) -> float:
        return self.random.betavariate(1.8, 1)


class HedgeboxMatrix(Matrix):
    PRODUCT_NAME = "Hedgebox"
    CLUSTER_CLASS = HedgeboxCluster
    PERSON_CLASS = HedgeboxPerson

    onboarding_experiment_start: dt.datetime
    onboarding_experiment_end: dt.datetime
    file_engagement_experiment_start: dt.datetime
    extended_end: dt.datetime

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Legacy experiment (complete) - runs from 30% to 60% of simulation
        self.onboarding_experiment_start = self.start + (self.now - self.start) * 0.3
        self.onboarding_experiment_end = self.start + (self.now - self.start) * 0.6

        # New experiment (running) - starts at 70% of simulation, extends beyond now
        self.file_engagement_experiment_start = self.start + (self.now - self.start) * 0.7

        # Extended simulation for running experiment
        self.extended_end = self.now + dt.timedelta(days=30)

    def set_project_up(self, team: "Team", user: "User"):
        super().set_project_up(team, user)
        team.autocapture_web_vitals_opt_in = True
        team.session_recording_opt_in = True  # Also see: the hedgebox-dummy/ app

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
            name="Visited Marius Tech Tips campaign",
            team=team,
            description="Visited page of the campaign we did with Marius Tech Tips, the best YouTube channel for tech tips.",
            created_by=user,
            steps_json=[{"event": "$pageview", "url": "/mariustechtips", "url_matching": "contains"}],
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
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_SIGNED_UP,
                            name=EVENT_SIGNED_UP,
                        )
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.ACTIONS_LINE_GRAPH,
                    ),
                    interval=IntervalType.WEEK,
                    dateRange=DateRange(
                        date_from="-8w",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_SIGNED_UP,
                            name=EVENT_SIGNED_UP,
                        )
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.WORLD_MAP,
                    ),
                    breakdownFilter=BreakdownFilter(
                        breakdown_type=BreakdownType.EVENT,
                        breakdown="$geoip_country_code",
                    ),
                    dateRange=DateRange(
                        date_from="-1m",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=FunnelsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_SIGNED_UP,
                            name=EVENT_SIGNED_UP,
                            custom_name="Signed up",
                        ),
                        ActionsNode(
                            id=interacted_with_file_action.pk,
                            name=interacted_with_file_action.name,
                        ),
                        EventsNode(
                            event=EVENT_UPGRADED_PLAN,
                            name=EVENT_UPGRADED_PLAN,
                            custom_name="Upgraded plan",
                        ),
                    ],
                    funnelsFilter=FunnelsFilter(
                        funnelVizType=FunnelVizType.STEPS,
                    ),
                    interval=IntervalType.DAY,
                    filterTestAccounts=True,
                    dateRange=DateRange(
                        date_from="-1m",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=RetentionQuery(
                    properties=[
                        PersonPropertyFilter(
                            key="email",
                            type=PropertyFilterType.PERSON,
                            operator=PropertyOperator.IS_SET,
                        )
                    ],
                    retentionFilter=RetentionFilter(
                        period=RetentionPeriod.WEEK,
                        display=ChartDisplayType.ACTIONS_TABLE,
                        retentionType=RetentionType.RETENTION_FIRST_TIME,
                        totalIntervals=9,
                        targetEntity=RetentionEntity(
                            id=EVENT_SIGNED_UP,
                            name=EVENT_SIGNED_UP,
                            type=EntityType.EVENTS,
                        ),
                        returningEntity=RetentionEntity(
                            id=str(interacted_with_file_action.pk),
                            name=interacted_with_file_action.name,
                            type=EntityType.ACTIONS,
                        ),
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=LifecycleQuery(
                    series=[
                        ActionsNode(
                            id=interacted_with_file_action.pk,
                            name=interacted_with_file_action.name,
                            math=BaseMathType.TOTAL,
                        )
                    ],
                    lifecycleFilter=LifecycleFilter(),
                    interval=IntervalType.DAY,
                    filterTestAccounts=True,
                    dateRange=DateRange(
                        date_from="-8w",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_UPLOADED_FILE,
                            name=EVENT_UPLOADED_FILE,
                            custom_name="Uploaded bytes",
                            math=PropertyMathType.SUM,
                            math_property="file_size_b",
                        ),
                        EventsNode(
                            event=EVENT_DELETED_FILE,
                            name=EVENT_DELETED_FILE,
                            custom_name="Deleted bytes",
                            math=PropertyMathType.SUM,
                            math_property="file_size_b",
                        ),
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.ACTIONS_LINE_GRAPH,
                    ),
                    interval=IntervalType.WEEK,
                    filterTestAccounts=True,
                    dateRange=DateRange(
                        date_from="-8w",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_PAID_BILL,
                            name=EVENT_PAID_BILL,
                            math=PropertyMathType.SUM,
                            math_property="amount_usd",
                        )
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.ACTIONS_LINE_GRAPH,
                    ),
                    interval=IntervalType.MONTH,
                    dateRange=DateRange(
                        date_from="-6m",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_PAID_BILL,
                            name="paid_bill",
                            math="unique_group",
                            math_group_type_index=0,
                        )
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.BOLD_NUMBER,
                    ),
                    compareFilter=CompareFilter(
                        compare=True,
                    ),
                    interval=IntervalType.DAY,
                    filterTestAccounts=True,
                    dateRange=DateRange(
                        date_from="-30d",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=PAGEVIEW_EVENT,
                            name=PAGEVIEW_EVENT,
                            math=BaseMathType.DAU,
                        )
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.ACTIONS_LINE_GRAPH,
                    ),
                    interval=IntervalType.DAY,
                    dateRange=DateRange(
                        date_from="-6m",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=PAGEVIEW_EVENT,
                            name=PAGEVIEW_EVENT,
                            math=BaseMathType.TOTAL,
                        )
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.ACTIONS_TABLE,
                    ),
                    breakdownFilter=BreakdownFilter(
                        breakdown="$current_url",
                        breakdown_type=BreakdownType.EVENT,
                    ),
                    properties=[
                        EventPropertyFilter(
                            key="$current_url",
                            type=PropertyFilterType.EVENT,
                            value="/files/",
                            operator=PropertyOperator.NOT_ICONTAINS,
                        )
                    ],
                    interval=IntervalType.DAY,
                    dateRange=DateRange(
                        date_from="-6m",
                    ),
                )
            ).model_dump(),
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
            query=InsightVizNode(
                source=FunnelsQuery(
                    series=[
                        EventsNode(
                            event="$pageview",
                            name="$pageview",
                            custom_name="Viewed homepage",
                            properties=[
                                EventPropertyFilter(
                                    key="$current_url",
                                    type=PropertyFilterType.EVENT,
                                    value=URL_HOME,
                                    operator="exact",
                                )
                            ],
                        ),
                        EventsNode(
                            event="$pageview",
                            name="$pageview",
                            custom_name="Viewed signup page",
                            properties=[
                                EventPropertyFilter(
                                    key="$current_url",
                                    type=PropertyFilterType.EVENT,
                                    value=URL_SIGNUP,
                                    operator="regex",
                                )
                            ],
                        ),
                        EventsNode(
                            event="signed_up",
                            name="signed_up",
                            custom_name="Signed up",
                        ),
                    ],
                    funnelsFilter=FunnelsFilter(
                        funnelVizType=FunnelVizType.STEPS,
                    ),
                    interval=IntervalType.DAY,
                    filterTestAccounts=True,
                    dateRange=DateRange(
                        date_from="-1m",
                    ),
                )
            ).model_dump(),
            last_modified_at=self.now - dt.timedelta(days=19),
            last_modified_by=user,
        )
        Insight.objects.create(
            team=team,
            saved=True,
            name="User paths starting at homepage",
            query=InsightVizNode(
                source=PathsQuery(
                    pathsFilter=PathsFilter(
                        edgeLimit=50,
                        stepLimit=5,
                        startPoint=URL_HOME,
                        excludeEvents=[],
                        pathGroupings=["/files/*"],
                        includeEventTypes=[PathType.FIELD_PAGEVIEW],
                        localPathCleaningFilters=[],
                    ),
                    dateRange=DateRange(
                        date_from="-30d",
                    ),
                )
            ).model_dump(),
            last_modified_at=self.now - dt.timedelta(days=9),
            last_modified_by=user,
        )
        Insight.objects.create(
            team=team,
            saved=True,
            name="File interactions",
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_UPLOADED_FILE,
                            name=EVENT_UPLOADED_FILE,
                        ),
                        EventsNode(
                            event=EVENT_DOWNLOADED_FILE,
                            name=EVENT_DOWNLOADED_FILE,
                        ),
                        EventsNode(
                            event=EVENT_DELETED_FILE,
                            name=EVENT_DELETED_FILE,
                        ),
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.ACTIONS_LINE_GRAPH,
                    ),
                    interval=IntervalType.DAY,
                    dateRange=DateRange(
                        date_from="-30d",
                    ),
                )
            ).model_dump(),
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
                    for insight in Insight.objects.filter(team__project_id=team.project_id)
                ),
            )
        except IntegrityError:
            pass  # This can happen if demo data generation is re-run for the same project

        # Feature flags
        try:
            FeatureFlag.objects.create(
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

            # LEGACY Experiment feature flag
            onboarding_flag = FeatureFlag.objects.create(
                team=team,
                key=ONBOARDING_EXPERIMENT_FLAG_KEY,
                name="Onboarding flow test",
                filters={
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 34},
                            {"key": "red", "rollout_percentage": 33},
                            {"key": "blue", "rollout_percentage": 33},
                        ]
                    },
                },
                created_by=user,
                created_at=self.onboarding_experiment_start - dt.timedelta(hours=1),
            )

            # Experiment feature flag
            file_engagement_flag = FeatureFlag.objects.create(
                team=team,
                key=FILE_ENGAGEMENT_FLAG_KEY,
                name="File engagement boost",
                filters={
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 34},
                            {"key": "red", "rollout_percentage": 33},
                            {"key": "blue", "rollout_percentage": 33},
                        ]
                    },
                },
                created_by=user,
                created_at=self.file_engagement_experiment_start - dt.timedelta(hours=2),
            )
        except IntegrityError:
            # Flags already exist, fetch them
            onboarding_flag = FeatureFlag.objects.get(team=team, key=ONBOARDING_EXPERIMENT_FLAG_KEY)
            file_engagement_flag = FeatureFlag.objects.get(team=team, key=FILE_ENGAGEMENT_FLAG_KEY)

        # Experiments and shared metrics

        # LEGACY Experiment and shared metrics

        # LEGACY Shared metrics
        legacy_shared_funnel = ExperimentSavedMetric.objects.create(
            team=team,
            name="z. Signup to payment",
            description="Monetization funnel: signup to first payment (legacy format)",
            query={
                "kind": "ExperimentFunnelsQuery",
                "name": "Signup to payment",
                "uuid": str(uuid.uuid4()),
                "funnels_query": {
                    "kind": "FunnelsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": EVENT_SIGNED_UP, "name": "Signed up"},
                        {"kind": "EventsNode", "event": EVENT_PAID_BILL, "name": "Paid bill"},
                    ],
                    "funnelsFilter": {
                        "layout": "horizontal",
                        "funnelVizType": "steps",
                        "funnelWindowInterval": 30,
                        "funnelWindowIntervalUnit": "day",
                        "funnelOrderType": "ordered",
                    },
                    "dateRange": {
                        "date_from": "-1m",
                        "date_to": None,
                    },
                    "filterTestAccounts": True,
                },
            },
            created_by=user,
        )

        legacy_shared_trend = ExperimentSavedMetric.objects.create(
            team=team,
            name="z. Revenue per user",
            description="Payment events per user (legacy format)",
            query={
                "kind": "ExperimentTrendsQuery",
                "name": "Revenue per user",
                "uuid": str(uuid.uuid4()),
                "count_query": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "name": EVENT_PAID_BILL,
                            "event": EVENT_PAID_BILL,
                        }
                    ],
                    "interval": "day",
                    "dateRange": {
                        "date_from": "-1m",
                        "date_to": None,
                        "explicitDate": True,
                    },
                    "trendsFilter": {
                        "display": "ActionsLineGraph",
                    },
                    "filterTestAccounts": True,
                },
            },
            created_by=user,
        )

        # LEGACY Experiment
        legacy_experiment = Experiment.objects.create(
            team=team,
            name="z. Onboarding flow test",
            description="Testing variations of our onboarding process to improve activation and engagement.",
            feature_flag=onboarding_flag,
            created_by=user,
            metrics=[
                {
                    "kind": "ExperimentFunnelsQuery",
                    "name": "Signup activation",
                    "uuid": str(uuid.uuid4()),
                    "funnels_query": {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": EVENT_SIGNED_UP, "name": "Signed up"},
                            {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE, "name": "Uploaded file"},
                        ],
                        "funnelsFilter": {
                            "layout": "horizontal",
                            "funnelVizType": "steps",
                            "funnelWindowInterval": 14,
                            "funnelWindowIntervalUnit": "day",
                            "funnelOrderType": "ordered",
                        },
                        "dateRange": {
                            "date_from": "-1m",
                            "date_to": None,
                        },
                        "filterTestAccounts": True,
                    },
                },
                {
                    "kind": "ExperimentTrendsQuery",
                    "name": "Signup count",
                    "uuid": str(uuid.uuid4()),
                    "count_query": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "kind": "EventsNode",
                                "name": EVENT_SIGNED_UP,
                                "event": EVENT_SIGNED_UP,
                            }
                        ],
                        "interval": "day",
                        "dateRange": {
                            "date_from": "-1m",
                            "date_to": None,
                            "explicitDate": True,
                        },
                        "trendsFilter": {
                            "display": "ActionsLineGraph",
                        },
                        "filterTestAccounts": True,
                    },
                },
            ],
            metrics_secondary=[],
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 34},
                    {"key": "red", "rollout_percentage": 33},
                    {"key": "blue", "rollout_percentage": 33},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.35),
                "minimum_detectable_effect": 15,
            },
            start_date=self.onboarding_experiment_start,
            end_date=self.onboarding_experiment_end,
            conclusion="won",
            conclusion_comment="The red variant demonstrated a 15% improvement in activation rate with statistical significance. Rolling out to all users.",
            created_at=onboarding_flag.created_at,
        )

        # Link ONLY legacy shared metrics to legacy experiment as secondary
        ExperimentToSavedMetric.objects.create(
            experiment=legacy_experiment,
            saved_metric=legacy_shared_funnel,
            metadata={"type": "secondary"},
        )
        ExperimentToSavedMetric.objects.create(
            experiment=legacy_experiment,
            saved_metric=legacy_shared_trend,
            metadata={"type": "secondary"},
        )

        # Experiments and shared metrics

        # Shared metrics
        new_shared_funnel = ExperimentSavedMetric.objects.create(
            team=team,
            name="Pageview engagement",
            description="Users who have multiple pageviews in a session",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "uuid": str(uuid.uuid4()),
                "series": [
                    {"kind": "EventsNode", "event": "$pageview"},
                    {"kind": "EventsNode", "event": "$pageview"},
                ],
                "goal": "increase",
                "conversion_window": 1,
                "conversion_window_unit": "day",
            },
            created_by=user,
        )

        new_shared_mean = ExperimentSavedMetric.objects.create(
            team=team,
            name="Files uploaded per user",
            description="Mean count of file uploads",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": str(uuid.uuid4()),
                "source": {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                "goal": "increase",
            },
            created_by=user,
        )

        new_shared_ratio = ExperimentSavedMetric.objects.create(
            team=team,
            name="Delete-to-upload ratio",
            description="Ratio of file deletions to uploads",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "ratio",
                "uuid": str(uuid.uuid4()),
                "numerator": {"kind": "EventsNode", "event": EVENT_DELETED_FILE},
                "denominator": {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                "goal": "increase",
            },
            created_by=user,
        )

        new_shared_retention = ExperimentSavedMetric.objects.create(
            team=team,
            name="7-day user retention",
            description="Users who return after 7 days",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "retention",
                "uuid": str(uuid.uuid4()),
                "goal": "increase",
                "start_event": {"kind": "EventsNode", "event": "$pageview"},
                "start_handling": "first_seen",
                "completion_event": {"kind": "EventsNode", "event": "$pageview", "math": "total"},
                "retention_window_start": 1,
                "retention_window_end": 7,
                "retention_window_unit": "day",
            },
            created_by=user,
        )

        new_experiment_metrics_ordered_uuids = [str(uuid.uuid4()) for _ in range(4)]

        # New experiment with one metric of each type, configured to show as many
        # different UI states as possible
        # Primary metrics are one time metrics, secondary metrics are shared metrics
        new_experiment = Experiment.objects.create(
            team=team,
            name="File engagement boost",
            description="Testing features to increase file uploads, sharing, and overall user engagement with files.",
            feature_flag=file_engagement_flag,
            created_by=user,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "uuid": new_experiment_metrics_ordered_uuids[0],
                    "name": "Upload activation",
                    "series": [
                        {"kind": "EventsNode", "event": "$pageview"},
                        {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                    ],
                    "goal": "increase",
                    "conversion_window": 7,
                    "conversion_window_unit": "day",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": new_experiment_metrics_ordered_uuids[1],
                    "name": "Active sessions per user",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                    "goal": "increase",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "uuid": new_experiment_metrics_ordered_uuids[2],
                    "name": "Download-to-upload ratio",
                    "numerator": {"kind": "EventsNode", "event": EVENT_DOWNLOADED_FILE},
                    "denominator": {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                    "goal": "increase",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "retention",
                    "uuid": new_experiment_metrics_ordered_uuids[3],
                    "name": "7-day user retention",
                    "goal": "increase",
                    "start_event": {"kind": "EventsNode", "event": "$pageview"},
                    "start_handling": "first_seen",
                    "completion_event": {"kind": "EventsNode", "event": "$pageview", "math": "total"},
                    "retention_window_start": 1,
                    "retention_window_end": 7,
                    "retention_window_unit": "day",
                },
            ],
            primary_metrics_ordered_uuids=new_experiment_metrics_ordered_uuids,
            secondary_metrics_ordered_uuids=[
                new_shared_funnel.query["uuid"],
                new_shared_mean.query["uuid"],
                new_shared_ratio.query["uuid"],
                new_shared_retention.query["uuid"],
            ],
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 34},
                    {"key": "red", "rollout_percentage": 33},
                    {"key": "blue", "rollout_percentage": 33},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.40),
                "minimum_detectable_effect": 10,
            },
            start_date=self.file_engagement_experiment_start,
            end_date=None,
            created_at=file_engagement_flag.created_at,
        )

        # Link ONLY new format shared metrics to new experiment as secondary
        for metric in [new_shared_funnel, new_shared_mean, new_shared_ratio, new_shared_retention]:
            ExperimentToSavedMetric.objects.create(
                experiment=new_experiment, saved_metric=metric, metadata={"type": "secondary"}
            )

        self._set_up_paid_bill_data_warehouse_table(team, user)

        # Create File Stats property group
        try:
            file_stats_group = SchemaPropertyGroup.objects.create(
                team=team,
                project=team.project,
                name="File Stats",
                description="",
                created_by=user,
            )

            SchemaPropertyGroupProperty.objects.create(
                property_group=file_stats_group,
                name="file_size_b",
                property_type=PropertyType.Numeric,
                is_required=True,
                description="",
            )

            SchemaPropertyGroupProperty.objects.create(
                property_group=file_stats_group,
                name="file_type",
                property_type=PropertyType.String,
                is_required=False,
                description="",
            )

            SchemaPropertyGroupProperty.objects.create(
                property_group=file_stats_group,
                name="file_name",
                property_type=PropertyType.String,
                is_required=False,
                description="",
            )

            uploaded_file_def = EventDefinition.objects.get_or_create(
                team=team, name=EVENT_UPLOADED_FILE, defaults={"team": team}
            )[0]
            downloaded_file_def = EventDefinition.objects.get_or_create(
                team=team, name=EVENT_DOWNLOADED_FILE, defaults={"team": team}
            )[0]

            EventSchema.objects.create(
                event_definition=uploaded_file_def,
                property_group=file_stats_group,
            )

            EventSchema.objects.create(
                event_definition=downloaded_file_def,
                property_group=file_stats_group,
            )
        except IntegrityError:
            pass

        if settings.OIDC_RSA_PRIVATE_KEY:
            try:
                OAuthApplication.objects.create(
                    name="Demo OAuth Application",
                    client_id="DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ",
                    client_secret="GQItUP4GqE6t5kjcWIRfWO9c0GXPCY8QDV4eszH4PnxXwCVxIMVSil4Agit7yay249jasnzHEkkVqHnFMxI1YTXSrh8Bj1sl1IDfNi1S95sv208NOc0eoUBP3TdA7vf0",
                    redirect_uris="http://localhost:3000/callback https://example.com/callback http://localhost:8237/callback http://localhost:8239/callback",
                    user=user,
                    organization=team.organization,
                    client_type=OAuthApplication.CLIENT_PUBLIC,
                    authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    algorithm="RS256",
                )
            except (IntegrityError, ValidationError):
                pass

    def _set_up_paid_bill_data_warehouse_table(self, team: "Team", user: "User") -> None:
        if settings.TEST or not settings.OBJECT_STORAGE_ENABLED:
            return

        access_key = settings.OBJECT_STORAGE_ACCESS_KEY_ID
        access_secret = settings.OBJECT_STORAGE_SECRET_ACCESS_KEY
        if not access_key or not access_secret or not settings.OBJECT_STORAGE_ENDPOINT:
            return

        try:
            rows = self._collect_paid_bill_rows(team.pk)
            s3_prefix = f"data-warehouse/demo_paid_bills/team_{team.pk}"
            object_key = f"{s3_prefix}/paid_bills.csv"
            object_storage.write(object_key, self._paid_bill_rows_to_csv(rows))

            credential = get_or_create_datawarehouse_credential(
                team_id=team.pk,
                access_key=access_key,
                access_secret=access_secret,
            )
            url_pattern = f"{self._warehouse_endpoint()}/{settings.OBJECT_STORAGE_BUCKET}/{s3_prefix}/*.csv"
            columns = {
                "id": "Int64",
                "distinct_id": "String",
                "timestamp": "DateTime",
                "amount_usd": "Float64",
                "plan": "String",
            }

            table_name = "paid_bills"
            existing_table = DataWarehouseTable.objects.filter(team=team, name=table_name).first()
            if existing_table:
                if existing_table.external_data_source is not None:
                    return
                existing_table.format = DataWarehouseTable.TableFormat.CSVWithNames
                existing_table.url_pattern = url_pattern
                existing_table.credential = credential
                existing_table.columns = columns
                existing_table.deleted = False
                existing_table.deleted_at = None
                if existing_table.created_by_id is None:
                    existing_table.created_by = user
                existing_table.save()
            else:
                DataWarehouseTable.objects.create(
                    team=team,
                    name=table_name,
                    format=DataWarehouseTable.TableFormat.CSVWithNames,
                    url_pattern=url_pattern,
                    credential=credential,
                    columns=columns,
                    created_by=user,
                )
        except Exception as err:
            capture_exception(err)

    def _collect_paid_bill_rows(self, team_id: int) -> list[tuple[int, str, str, float, str]]:
        if self.is_complete:
            rows: list[tuple[int, str, str, float, str]] = []
            row_id = 1
            for person in self.people:
                for event in person.past_events:
                    if event.event != EVENT_PAID_BILL:
                        continue
                    amount_usd = event.properties.get("amount_usd")
                    rows.append(
                        (
                            row_id,
                            event.distinct_id,
                            self._format_warehouse_timestamp(event.timestamp),
                            float(amount_usd) if amount_usd is not None else 0.0,
                            str(event.properties.get("plan") or ""),
                        )
                    )
                    row_id += 1
            return rows

        query = """
            SELECT
                toInt64(cityHash64(toString(uuid))) AS id,
                distinct_id,
                toString(timestamp) AS timestamp,
                JSONExtractFloat(properties, 'amount_usd') AS amount_usd,
                JSONExtractString(properties, 'plan') AS plan
            FROM events
            WHERE team_id = %(team_id)s
                AND event = %(event)s
            ORDER BY timestamp
        """
        results = query_with_columns(
            query,
            {"team_id": team_id, "event": EVENT_PAID_BILL},
        )
        return [
            (
                int(row["id"]),
                row["distinct_id"],
                row["timestamp"],
                float(row["amount_usd"]),
                row["plan"] or "",
            )
            for row in results
        ]

    @staticmethod
    def _paid_bill_rows_to_csv(rows: list[tuple[int, str, str, float, str]]) -> str:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "distinct_id", "timestamp", "amount_usd", "plan"])
        writer.writerows(rows)
        return output.getvalue()

    @staticmethod
    def _format_warehouse_timestamp(value: dt.datetime) -> str:
        if value.tzinfo is None:
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _warehouse_endpoint() -> str:
        endpoint = settings.OBJECT_STORAGE_ENDPOINT.rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.hostname not in {"localhost", "127.0.0.1"}:
            return endpoint
        host = "host.docker.internal"
        netloc = f"{host}:{parsed.port}" if parsed.port else host
        return urlunparse(parsed._replace(netloc=netloc))
