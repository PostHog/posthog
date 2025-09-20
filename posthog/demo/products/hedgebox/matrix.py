import datetime as dt
from dataclasses import dataclass
from typing import Optional

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
    MrrOrGross,
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
    RevenueAnalyticsEventItem,
    RevenueAnalyticsGoal,
    TrendsFilter,
    TrendsQuery,
)

from posthog.constants import PAGEVIEW_EVENT
from posthog.demo.matrix.matrix import Cluster, Matrix
from posthog.demo.matrix.randomization import Industry
from posthog.models import Action, Cohort, Dashboard, DashboardTile, Experiment, FeatureFlag, Insight, InsightViewed

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
    FILE_PREVIEWS_FLAG_KEY,
    NEW_SIGNUP_PAGE_FLAG_KEY,
    NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT,
    URL_HOME,
    URL_SIGNUP,
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
        return self.company.name if self.company else f"Social Circle #{self.index + 1}"

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
        team.autocapture_web_vitals_opt_in = True

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

        # Configure Revenue analytics events
        team.revenue_analytics_config.goals = [
            RevenueAnalyticsGoal(
                due_date=f"{dt.datetime.now().year}-12-31",
                goal=1000,
                mrr_or_gross=MrrOrGross.GROSS,
                name=f"{dt.datetime.now().year} Q4",
            )
        ]
        team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName=EVENT_PAID_BILL,
                revenueProperty="amount_usd",
                productProperty="plan",
            )
        ]
        team.revenue_analytics_config.save()
