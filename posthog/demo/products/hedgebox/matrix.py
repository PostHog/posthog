import csv
import uuid
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, Any, Optional, cast
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

from posthog.constants import PAGEVIEW_EVENT
from posthog.demo.matrix.matrix import Cluster, Matrix
from posthog.demo.matrix.models import SimEvent
from posthog.demo.matrix.randomization import Industry
from posthog.exceptions_capture import capture_exception
from posthog.models import Action, Cohort, FeatureFlag, Insight, InsightViewed
from posthog.models.oauth import OAuthApplication
from posthog.storage import object_storage

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.data_warehouse.backend.models.credential import get_or_create_datawarehouse_credential
from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.property_definition import PropertyType
from products.event_definitions.backend.models.schema import (
    EventSchema,
    SchemaPropertyGroup,
    SchemaPropertyGroupProperty,
)
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric

from .models import HedgeboxAccount, HedgeboxPerson
from .taxonomy import (
    COMPANY_CLUSTERS_PROPORTION,
    EVENT_DELETED_FILE,
    EVENT_DOWNGRADED_PLAN,
    EVENT_DOWNLOADED_FILE,
    EVENT_LOGGED_IN,
    EVENT_PAID_BILL,
    EVENT_SHARED_FILE_LINK,
    EVENT_SIGNED_UP,
    EVENT_UPGRADED_PLAN,
    EVENT_UPLOADED_FILE,
    FLAG_FILE_ENGAGEMENT_EXPERIMENT,
    FLAG_FILE_PREVIEWS,
    FLAG_ONBOARDING_EXPERIMENT,
    FLAG_PRICING_PAGE_EXPERIMENT,
    FLAG_RETENTION_NUDGE_EXPERIMENT,
    FLAG_SHARING_INCENTIVE_EXPERIMENT,
    FLAG_TEAM_COLLAB_EXPERIMENT,
    FLAG_UPGRADE_PROMPT_EXPERIMENT,
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


@dataclass(frozen=True)
class DemoDataWarehouseTableSpec:
    name: str
    columns: dict[str, str]
    source_events: tuple[str, ...]
    row_builder: Callable[[SimEvent, int], tuple[Any, ...]]


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
    pricing_experiment_start: dt.datetime
    pricing_experiment_end: dt.datetime
    sharing_experiment_start: dt.datetime
    sharing_experiment_end: dt.datetime
    upgrade_prompt_experiment_start: dt.datetime
    team_collab_experiment_start: dt.datetime
    team_collab_experiment_end: dt.datetime
    extended_end: dt.datetime

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        elapsed = self.now - self.start

        # Legacy experiment (complete) - runs from 30% to 60% of simulation
        self.onboarding_experiment_start = self.start + elapsed * 0.3
        self.onboarding_experiment_end = self.start + elapsed * 0.6

        # New experiment (running) - starts at 70% of simulation, extends beyond now
        self.file_engagement_experiment_start = self.start + elapsed * 0.7

        # Pricing page redesign (inconclusive) - 15% to 45%
        self.pricing_experiment_start = self.start + elapsed * 0.15
        self.pricing_experiment_end = self.start + elapsed * 0.45

        # File sharing incentive (lost) - 40% to 65%
        self.sharing_experiment_start = self.start + elapsed * 0.4
        self.sharing_experiment_end = self.start + elapsed * 0.65

        # Upgrade prompt (running, recent) - 90% onward
        self.upgrade_prompt_experiment_start = self.start + elapsed * 0.9

        # Team collaboration boost (stopped early) - 50% to 70%
        self.team_collab_experiment_start = self.start + elapsed * 0.5
        self.team_collab_experiment_end = self.start + elapsed * 0.7

        # Extended simulation for running experiment
        self.extended_end = self.now + dt.timedelta(days=30)

    def set_project_up(self, team: "Team", user: "User"):
        super().set_project_up(team, user)
        team.autocapture_web_vitals_opt_in = True
        team.session_recording_opt_in = True  # Also see: the tools/hedgebox-dummy/ app

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
        # Create the standard internal/test users cohort (same as non-demo teams get)
        from posthog.models.cohort.cohort import get_or_create_internal_test_users_cohort

        test_users_cohort = get_or_create_internal_test_users_cohort(team, initiating_user_email=user.email)
        team.test_account_filters = [
            {"key": "id", "type": "cohort", "value": test_users_cohort.pk, "operator": "not_in"},
        ]

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
        def create_experiment_flag(
            key: str, name: str, variants: list[tuple[str, int]], created_at: dt.datetime
        ) -> FeatureFlag:
            return FeatureFlag.objects.create(
                team=team,
                key=key,
                name=name,
                filters={
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {"variants": [{"key": k, "rollout_percentage": pct} for k, pct in variants]},
                },
                created_by=user,
                created_at=created_at,
            )

        try:
            FeatureFlag.objects.create(
                team=team,
                key=FLAG_FILE_PREVIEWS,
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

            # Experiment feature flags
            onboarding_flag = create_experiment_flag(
                FLAG_ONBOARDING_EXPERIMENT,
                "Onboarding flow test",
                [("control", 34), ("red", 33), ("blue", 33)],
                self.onboarding_experiment_start - dt.timedelta(hours=1),
            )
            file_engagement_flag = create_experiment_flag(
                FLAG_FILE_ENGAGEMENT_EXPERIMENT,
                "File engagement boost",
                [("control", 34), ("red", 33), ("blue", 33)],
                self.file_engagement_experiment_start - dt.timedelta(hours=2),
            )
            pricing_flag = create_experiment_flag(
                FLAG_PRICING_PAGE_EXPERIMENT,
                "Pricing page redesign",
                [("control", 50), ("test", 50)],
                self.pricing_experiment_start - dt.timedelta(hours=1),
            )
            sharing_flag = create_experiment_flag(
                FLAG_SHARING_INCENTIVE_EXPERIMENT,
                "File sharing incentive",
                [("control", 50), ("test", 50)],
                self.sharing_experiment_start - dt.timedelta(hours=1),
            )
            upgrade_prompt_flag = create_experiment_flag(
                FLAG_UPGRADE_PROMPT_EXPERIMENT,
                "Upgrade prompt experiment",
                [("control", 34), ("aggressive", 33), ("subtle", 33)],
                self.upgrade_prompt_experiment_start - dt.timedelta(hours=1),
            )
            retention_nudge_flag = create_experiment_flag(
                FLAG_RETENTION_NUDGE_EXPERIMENT,
                "Retention nudge",
                [("control", 50), ("test", 50)],
                self.now - dt.timedelta(days=2),
            )
            team_collab_flag = create_experiment_flag(
                FLAG_TEAM_COLLAB_EXPERIMENT,
                "Team collaboration boost",
                [("control", 50), ("test", 50)],
                self.team_collab_experiment_start - dt.timedelta(hours=1),
            )
        except IntegrityError:
            # Flags already exist, fetch them
            onboarding_flag = FeatureFlag.objects.get(team=team, key=FLAG_ONBOARDING_EXPERIMENT)
            file_engagement_flag = FeatureFlag.objects.get(team=team, key=FLAG_FILE_ENGAGEMENT_EXPERIMENT)
            pricing_flag = FeatureFlag.objects.get(team=team, key=FLAG_PRICING_PAGE_EXPERIMENT)
            sharing_flag = FeatureFlag.objects.get(team=team, key=FLAG_SHARING_INCENTIVE_EXPERIMENT)
            upgrade_prompt_flag = FeatureFlag.objects.get(team=team, key=FLAG_UPGRADE_PROMPT_EXPERIMENT)
            retention_nudge_flag = FeatureFlag.objects.get(team=team, key=FLAG_RETENTION_NUDGE_EXPERIMENT)
            team_collab_flag = FeatureFlag.objects.get(team=team, key=FLAG_TEAM_COLLAB_EXPERIMENT)

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
            scheduling_config={"timeseries": True},
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
            scheduling_config={"timeseries": True},
            start_date=self.file_engagement_experiment_start,
            end_date=None,
            created_at=file_engagement_flag.created_at,
        )

        # Link ONLY new format shared metrics to new experiment as secondary
        for metric in [new_shared_funnel, new_shared_mean, new_shared_ratio, new_shared_retention]:
            ExperimentToSavedMetric.objects.create(
                experiment=new_experiment, saved_metric=metric, metadata={"type": "secondary"}
            )

        # --- Additional experiments for coverage of various states ---

        # Pricing page redesign (inconclusive) — uses high-volume pageview→signup funnel
        Experiment.objects.create(
            team=team,
            name="Pricing page redesign",
            description="Testing a simplified pricing page layout to improve signup conversion from the pricing page.",
            feature_flag=pricing_flag,
            created_by=user,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "uuid": str(uuid.uuid4()),
                    "name": "Pricing page to signup",
                    "series": [
                        {"kind": "EventsNode", "event": "$pageview"},
                        {"kind": "EventsNode", "event": EVENT_SIGNED_UP},
                    ],
                    "goal": "increase",
                    "conversion_window": 14,
                    "conversion_window_unit": "day",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": str(uuid.uuid4()),
                    "name": "Pageviews per user",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                    "goal": "increase",
                },
            ],
            metrics_secondary=[],
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.30),
                "minimum_detectable_effect": 10,
            },
            start_date=self.pricing_experiment_start,
            end_date=self.pricing_experiment_end,
            conclusion="inconclusive",
            conclusion_comment="No statistically significant difference detected between the control and test variants after the full run. Needs a larger sample size or bolder design change.",
            created_at=pricing_flag.created_at,
        )

        # File sharing incentive (lost) — uses upload→download funnel and upload mean
        Experiment.objects.create(
            team=team,
            name="File sharing incentive",
            description="Testing whether a sharing prompt after upload increases file engagement and downloads.",
            feature_flag=sharing_flag,
            created_by=user,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": str(uuid.uuid4()),
                    "name": "Uploads per user",
                    "source": {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                    "goal": "increase",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "uuid": str(uuid.uuid4()),
                    "name": "Upload to download",
                    "series": [
                        {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                        {"kind": "EventsNode", "event": EVENT_DOWNLOADED_FILE},
                    ],
                    "goal": "increase",
                    "conversion_window": 7,
                    "conversion_window_unit": "day",
                },
            ],
            metrics_secondary=[],
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.25),
                "minimum_detectable_effect": 12,
            },
            start_date=self.sharing_experiment_start,
            end_date=self.sharing_experiment_end,
            conclusion="lost",
            conclusion_comment="The sharing prompt annoyed users and led to fewer uploads overall. The test variant performed significantly worse than control.",
            created_at=sharing_flag.created_at,
        )

        # Upgrade prompt experiment (running, recently started) — uses high-volume events
        Experiment.objects.create(
            team=team,
            name="Upgrade prompt experiment",
            description="Testing different prompt styles to increase user engagement and file activity.",
            feature_flag=upgrade_prompt_flag,
            created_by=user,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "uuid": str(uuid.uuid4()),
                    "name": "Login to upload",
                    "series": [
                        {"kind": "EventsNode", "event": EVENT_LOGGED_IN},
                        {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                    ],
                    "goal": "increase",
                    "conversion_window": 7,
                    "conversion_window_unit": "day",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": str(uuid.uuid4()),
                    "name": "Downloads per user",
                    "source": {"kind": "EventsNode", "event": EVENT_DOWNLOADED_FILE},
                    "goal": "increase",
                },
            ],
            metrics_secondary=[],
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 34},
                    {"key": "aggressive", "rollout_percentage": 33},
                    {"key": "subtle", "rollout_percentage": 33},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.35),
                "minimum_detectable_effect": 15,
            },
            start_date=self.upgrade_prompt_experiment_start,
            end_date=None,
            created_at=upgrade_prompt_flag.created_at,
        )

        # Retention nudge (draft - not yet started)
        Experiment.objects.create(
            team=team,
            name="Retention nudge",
            description="Planning to test email and in-app nudges for users who haven't logged in for 3+ days.",
            feature_flag=retention_nudge_flag,
            created_by=user,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "retention",
                    "uuid": str(uuid.uuid4()),
                    "name": "7-day login retention",
                    "goal": "increase",
                    "start_event": {"kind": "EventsNode", "event": EVENT_LOGGED_IN},
                    "start_handling": "first_seen",
                    "completion_event": {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE, "math": "total"},
                    "retention_window_start": 1,
                    "retention_window_end": 7,
                    "retention_window_unit": "day",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": str(uuid.uuid4()),
                    "name": "Downloads per user",
                    "source": {"kind": "EventsNode", "event": EVENT_DOWNLOADED_FILE},
                    "goal": "increase",
                },
            ],
            metrics_secondary=[],
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.30),
                "minimum_detectable_effect": 10,
            },
            start_date=None,
            end_date=None,
            created_at=retention_nudge_flag.created_at,
        )

        # Team collaboration boost (stopped early) — uses high-volume events
        Experiment.objects.create(
            team=team,
            name="Team collaboration boost",
            description="Testing a team activity feed to encourage more file uploads and engagement.",
            feature_flag=team_collab_flag,
            created_by=user,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": str(uuid.uuid4()),
                    "name": "Files uploaded per user",
                    "source": {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                    "goal": "increase",
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "uuid": str(uuid.uuid4()),
                    "name": "Signup to upload",
                    "series": [
                        {"kind": "EventsNode", "event": EVENT_SIGNED_UP},
                        {"kind": "EventsNode", "event": EVENT_UPLOADED_FILE},
                    ],
                    "goal": "increase",
                    "conversion_window": 7,
                    "conversion_window_unit": "day",
                },
            ],
            metrics_secondary=[],
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
                "recommended_sample_size": int(len(self.clusters) * 0.30),
                "minimum_detectable_effect": 12,
            },
            start_date=self.team_collab_experiment_start,
            end_date=self.team_collab_experiment_end,
            conclusion="stopped_early",
            conclusion_comment="Stopped early due to a bug in the activity feed causing excessive notifications. Need to fix the notification throttling before re-running.",
            created_at=team_collab_flag.created_at,
        )

        self._set_up_demo_data_warehouse_tables(team, user)

        # Endpoints
        try:
            weekly_signups_endpoint = Endpoint.objects.create(
                name="weekly-signups",
                team=team,
                created_by=user,
                is_active=True,
                current_version=1,
            )
            EndpointVersion.objects.create(
                endpoint=weekly_signups_endpoint,
                version=1,
                query=TrendsQuery(
                    series=[EventsNode(event=EVENT_SIGNED_UP, name=EVENT_SIGNED_UP)],
                    trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
                    interval=IntervalType.WEEK,
                    dateRange=DateRange(date_from="-8w"),
                ).model_dump(),
                description="Weekly signup count over the last 8 weeks",
                created_by=user,
            )

            monthly_revenue_endpoint = Endpoint.objects.create(
                name="monthly-revenue",
                team=team,
                created_by=user,
                is_active=True,
                current_version=1,
            )
            EndpointVersion.objects.create(
                endpoint=monthly_revenue_endpoint,
                version=1,
                query=TrendsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_PAID_BILL,
                            name=EVENT_PAID_BILL,
                            math=PropertyMathType.SUM,
                            math_property="amount_usd",
                        )
                    ],
                    trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
                    interval=IntervalType.MONTH,
                    dateRange=DateRange(date_from="-6m"),
                ).model_dump(),
                description="Monthly revenue from paid bills over the last 6 months",
                created_by=user,
            )

            signups_by_country_endpoint = Endpoint.objects.create(
                name="signups-by-country",
                team=team,
                created_by=user,
                is_active=True,
                current_version=1,
            )
            EndpointVersion.objects.create(
                endpoint=signups_by_country_endpoint,
                version=1,
                query=TrendsQuery(
                    series=[EventsNode(event=EVENT_SIGNED_UP, name=EVENT_SIGNED_UP)],
                    trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_TABLE),
                    breakdownFilter=BreakdownFilter(
                        breakdown="$geoip_country_code",
                        breakdown_type=BreakdownType.EVENT,
                    ),
                    dateRange=DateRange(date_from="-30d"),
                ).model_dump(),
                description="Signups broken down by country over the last 30 days",
                created_by=user,
            )

            daily_active_users_endpoint = Endpoint.objects.create(
                name="daily-active-users",
                team=team,
                created_by=user,
                is_active=True,
                current_version=1,
            )
            EndpointVersion.objects.create(
                endpoint=daily_active_users_endpoint,
                version=1,
                query={
                    "kind": "HogQLQuery",
                    "query": (
                        "SELECT toDate(timestamp) AS day, count(DISTINCT person_id) AS unique_users "
                        "FROM events WHERE event = '$pageview' AND timestamp >= now() - interval 30 day "
                        "GROUP BY day ORDER BY day"
                    ),
                },
                description="Daily active users (unique pageview persons) over the last 30 days",
                created_by=user,
            )

            activation_funnel_endpoint = Endpoint.objects.create(
                name="activation-funnel",
                team=team,
                created_by=user,
                is_active=True,
                current_version=1,
            )
            EndpointVersion.objects.create(
                endpoint=activation_funnel_endpoint,
                version=1,
                query=FunnelsQuery(
                    series=[
                        EventsNode(
                            event=EVENT_SIGNED_UP,
                            name=EVENT_SIGNED_UP,
                            custom_name="Signed up",
                        ),
                        EventsNode(
                            event=EVENT_UPLOADED_FILE,
                            name=EVENT_UPLOADED_FILE,
                            custom_name="Uploaded file",
                        ),
                        EventsNode(
                            event=EVENT_UPGRADED_PLAN,
                            name=EVENT_UPGRADED_PLAN,
                            custom_name="Upgraded plan",
                        ),
                    ],
                    funnelsFilter=FunnelsFilter(funnelVizType=FunnelVizType.STEPS),
                    dateRange=DateRange(date_from="-30d"),
                ).model_dump(),
                description="Activation funnel from signup through file upload to plan upgrade",
                created_by=user,
            )
        except IntegrityError:
            pass

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

    def _set_up_demo_data_warehouse_tables(self, team: "Team", user: "User") -> None:
        if settings.TEST or not settings.OBJECT_STORAGE_ENABLED:
            return

        access_key = settings.OBJECT_STORAGE_ACCESS_KEY_ID
        access_secret = settings.OBJECT_STORAGE_SECRET_ACCESS_KEY
        if not access_key or not access_secret or not settings.OBJECT_STORAGE_ENDPOINT:
            return

        credential = get_or_create_datawarehouse_credential(
            team_id=team.pk,
            access_key=access_key,
            access_secret=access_secret,
        )
        for table_spec in self._demo_data_warehouse_table_specs():
            try:
                rows = self._collect_demo_data_warehouse_rows(table_spec)
                self._upsert_demo_data_warehouse_table(team, user, credential, table_spec, rows)
            except Exception as err:
                capture_exception(err)

        try:
            self._upsert_demo_extended_person_properties_table(team, user, credential)
        except Exception as err:
            capture_exception(err)

    def _demo_data_warehouse_table_specs(self) -> tuple[DemoDataWarehouseTableSpec, ...]:
        return (
            DemoDataWarehouseTableSpec(
                name="paid_bills",
                columns={
                    "id": "Int64",
                    "distinct_id": "String",
                    "timestamp": "DateTime",
                    "amount_usd": "Float64",
                    "plan": "String",
                },
                source_events=(EVENT_PAID_BILL,),
                row_builder=self._paid_bill_row,
            ),
            DemoDataWarehouseTableSpec(
                name="signups",
                columns={
                    "id": "Int64",
                    "distinct_id": "String",
                    "timestamp": "DateTime",
                    "from_invite": "Bool",
                },
                source_events=(EVENT_SIGNED_UP,),
                row_builder=self._signup_row,
            ),
            DemoDataWarehouseTableSpec(
                name="uploaded_files",
                columns={
                    "id": "Int64",
                    "distinct_id": "String",
                    "timestamp": "DateTime",
                    "file_type": "String",
                    "file_size_b": "Int64",
                    "used_mb": "Float64",
                    "file_name": "String",
                },
                source_events=(EVENT_UPLOADED_FILE,),
                row_builder=self._uploaded_file_row,
            ),
            DemoDataWarehouseTableSpec(
                name="plan_changes",
                columns={
                    "id": "Int64",
                    "distinct_id": "String",
                    "timestamp": "DateTime",
                    "change_type": "String",
                    "previous_plan": "String",
                    "new_plan": "String",
                },
                source_events=(EVENT_UPGRADED_PLAN, EVENT_DOWNGRADED_PLAN),
                row_builder=self._plan_change_row,
            ),
        )

    def _collect_demo_data_warehouse_rows(self, table_spec: DemoDataWarehouseTableSpec) -> list[tuple[Any, ...]]:
        if not self.is_complete:
            raise ValueError("Demo data warehouse tables require a completed simulation.")

        matching_events = sorted(
            (
                event
                for person in self.people
                for event in person.past_events
                if event.event in table_spec.source_events
            ),
            key=lambda event: (event.timestamp, event.distinct_id, event.event),
        )
        return [table_spec.row_builder(event, row_id) for row_id, event in enumerate(matching_events, start=1)]

    @staticmethod
    def _demo_extended_person_properties_columns() -> dict[str, str]:
        return {
            "id": "Int64",
            "email": "String",
            "hedgebox_user_id": "String",
            "company_name": "String",
            "industry": "String",
            "account_kind": "String",
            "current_plan": "String",
            "team_size": "Int64",
            "file_count": "Int64",
            "used_mb": "Float64",
            "allocation_used_fraction": "Float64",
            "monthly_bill_usd": "Float64",
            "lifecycle_stage": "String",
            "onboarding_variant": "String",
            "file_engagement_variant": "String",
            "watches_marius_tech_tips": "Bool",
            "is_invitable": "Bool",
        }

    def _collect_demo_extended_person_rows(self) -> list[tuple[Any, ...]]:
        if not self.is_complete:
            raise ValueError("Demo data warehouse tables require a completed simulation.")

        rows: list[tuple[Any, ...]] = []
        people = cast(list[HedgeboxPerson], self.people)

        for person in sorted(people, key=lambda current_person: current_person.in_product_id):
            if not hasattr(person, "properties_at_now"):
                person.take_snapshot_at_now()

            email = person.properties_at_now.get("email")
            if not email:
                continue

            account = person.account
            team_size = len(account.team_members) if account else 0
            file_count = len(account.files) if account else 0

            if file_count >= 5:
                lifecycle_stage = "power_user"
            elif file_count > 0:
                lifecycle_stage = "activated"
            else:
                lifecycle_stage = "signed_up"

            rows.append(
                (
                    len(rows) + 1,
                    str(email),
                    person.in_product_id,
                    person.cluster.company.name if person.cluster.company else person.name,
                    str(person.cluster.company.industry) if person.cluster.company else "consumer",
                    "business" if person.cluster.company else "personal",
                    str(account.plan) if account else "",
                    team_size,
                    file_count,
                    float(account.current_used_mb) if account else 0.0,
                    float(account.allocation_used_fraction) if account else 0.0,
                    float(account.current_monthly_bill_usd) if account else 0.0,
                    lifecycle_stage,
                    person.onboarding_variant,
                    person.file_engagement_variant,
                    person.watches_marius_tech_tips,
                    person.is_invitable,
                )
            )

        return rows

    def _upsert_demo_extended_person_properties_table(self, team: "Team", user: "User", credential) -> None:
        table_name = "extended_properties"
        rows = self._collect_demo_extended_person_rows()
        self._upsert_demo_data_warehouse_table_contents(
            team=team,
            user=user,
            credential=credential,
            table_name=table_name,
            columns=self._demo_extended_person_properties_columns(),
            rows=rows,
        )
        self._upsert_demo_extended_person_properties_join(team, table_name)

    @staticmethod
    def _upsert_demo_extended_person_properties_join(team: "Team", table_name: str) -> None:
        existing_join = (
            DataWarehouseJoin.objects.filter(
                team=team,
                source_table_name="persons",
                source_table_key="properties.email",
                joining_table_name=table_name,
                joining_table_key="email",
                field_name=table_name,
            )
            .order_by("-created_at")
            .first()
        )

        if existing_join:
            existing_join.deleted = False
            existing_join.deleted_at = None
            existing_join.save()
            return

        DataWarehouseJoin.objects.create(
            team=team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name=table_name,
            joining_table_key="email",
            field_name=table_name,
        )

    def _upsert_demo_data_warehouse_table(
        self,
        team: "Team",
        user: "User",
        credential,
        table_spec: DemoDataWarehouseTableSpec,
        rows: list[tuple[Any, ...]],
    ) -> None:
        self._upsert_demo_data_warehouse_table_contents(
            team=team,
            user=user,
            credential=credential,
            table_name=table_spec.name,
            columns=table_spec.columns,
            rows=rows,
        )

    def _upsert_demo_data_warehouse_table_contents(
        self,
        team: "Team",
        user: "User",
        credential,
        table_name: str,
        columns: dict[str, str],
        rows: list[tuple[Any, ...]],
    ) -> None:
        s3_prefix = f"data-warehouse/demo_{table_name}/team_{team.pk}"
        object_key = f"{s3_prefix}/{table_name}.csv"
        object_storage.write(object_key, self._warehouse_rows_to_csv(rows, headers=tuple(columns.keys())))

        url_pattern = f"{self._warehouse_endpoint()}/{settings.OBJECT_STORAGE_BUCKET}/{s3_prefix}/*.csv"
        existing_table = DataWarehouseTable.objects.filter(team=team, name=table_name).first()
        if existing_table:
            if existing_table.external_data_source is not None:
                return
            existing_table.format = DataWarehouseTable.TableFormat.CSVWithNames
            existing_table.url_pattern = url_pattern
            existing_table.credential = credential
            existing_table.columns = columns
            existing_table.options = {**(existing_table.options or {}), "csv_allow_double_quotes": True}
            existing_table.deleted = False
            existing_table.deleted_at = None
            if existing_table.created_by_id is None:
                existing_table.created_by = user
            existing_table.save()
            return

        DataWarehouseTable.objects.create(
            team=team,
            name=table_name,
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            url_pattern=url_pattern,
            credential=credential,
            columns=columns,
            options={"csv_allow_double_quotes": True},
            created_by=user,
        )

    @classmethod
    def _paid_bill_row(cls, event: SimEvent, row_id: int) -> tuple[int, str, str, float, str]:
        amount_usd = event.properties.get("amount_usd")
        return (
            row_id,
            event.distinct_id,
            cls._format_warehouse_timestamp(event.timestamp),
            float(amount_usd) if amount_usd is not None else 0.0,
            str(event.properties.get("plan") or ""),
        )

    @classmethod
    def _signup_row(cls, event: SimEvent, row_id: int) -> tuple[int, str, str, bool]:
        return (
            row_id,
            event.distinct_id,
            cls._format_warehouse_timestamp(event.timestamp),
            bool(event.properties.get("from_invite", False)),
        )

    @classmethod
    def _uploaded_file_row(cls, event: SimEvent, row_id: int) -> tuple[int, str, str, str, int, float, str]:
        file_size_b = event.properties.get("file_size_b")
        used_mb = event.properties.get("used_mb")
        return (
            row_id,
            event.distinct_id,
            cls._format_warehouse_timestamp(event.timestamp),
            str(event.properties.get("file_type") or ""),
            int(file_size_b) if file_size_b is not None else 0,
            float(used_mb) if used_mb is not None else 0.0,
            str(event.properties.get("file_name") or ""),
        )

    @classmethod
    def _plan_change_row(cls, event: SimEvent, row_id: int) -> tuple[int, str, str, str, str, str]:
        return (
            row_id,
            event.distinct_id,
            cls._format_warehouse_timestamp(event.timestamp),
            "upgrade" if event.event == EVENT_UPGRADED_PLAN else "downgrade",
            str(event.properties.get("previous_plan") or ""),
            str(event.properties.get("new_plan") or ""),
        )

    @staticmethod
    def _warehouse_rows_to_csv(rows: list[tuple[Any, ...]], headers: tuple[str, ...]) -> str:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
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
