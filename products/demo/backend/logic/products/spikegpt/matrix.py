import datetime as dt

from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    ChartSettings,
    DataVisualizationNode,
    DateRange,
    EventsNode,
    GradientScaleMode,
    HeatmapGradientStop,
    HeatmapSettings,
    HogQLQuery,
    InsightVizNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from products.cohorts.backend.models.cohort import Cohort
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.demo.backend.logic.matrix.matrix import Cluster, Matrix
from products.product_analytics.backend.models.insight import Insight

from .models import SpikeGPTPerson

# Column aliases must match the chartSettings.heatmap columns of the insights below —
# the 2d heatmap matches result columns to axes by alias string
LATENCY_HEATMAP_SQL = """
SELECT
    properties.$ai_provider AS provider,
    properties.$ai_span_name AS task,
    round(avg(toFloat(properties.$ai_latency)), 2) AS avg_latency_s
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY AND timestamp <= now()
GROUP BY provider, task
ORDER BY provider, task
""".strip()

COST_HEATMAP_SQL = """
SELECT
    properties.$ai_provider AS provider,
    properties.$ai_span_name AS task,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 2) AS total_cost_usd
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY AND timestamp <= now()
GROUP BY provider, task
ORDER BY provider, task
""".strip()

# Stops copied from the "reds"/"blues" presets in
# frontend/src/queries/nodes/DataVisualization/Components/Heatmap/heatmapUtils.ts —
# the renderer reads gradient stops, gradientPreset is only UI state
REDS_GRADIENT = [
    HeatmapGradientStop(value=0.0, color="#FFF5F0"),
    HeatmapGradientStop(value=0.25, color="#FEE0D2"),
    HeatmapGradientStop(value=0.5, color="#FC9272"),
    HeatmapGradientStop(value=0.75, color="#DE2D26"),
    HeatmapGradientStop(value=1.0, color="#A50F15"),
]
BLUES_GRADIENT = [
    HeatmapGradientStop(value=0.0, color="#F7FBFF"),
    HeatmapGradientStop(value=0.25, color="#DEEBF7"),
    HeatmapGradientStop(value=0.5, color="#9ECAE1"),
    HeatmapGradientStop(value=0.75, color="#4292C6"),
    HeatmapGradientStop(value=1.0, color="#08519C"),
]


class SpikeGPTCluster(Cluster):
    matrix: "SpikeGPTMatrix"

    MIN_RADIUS: int = 0
    MAX_RADIUS: int = 0

    def __str__(self) -> str:
        return f"Social Circle #{self.index + 1}"

    def radius_distribution(self) -> float:
        return self.random.betavariate(1.5, 5)

    def initiation_distribution(self) -> float:
        return self.random.betavariate(1.8, 1)


class SpikeGPTMatrix(Matrix):
    PRODUCT_NAME = "SpikeGPT"
    CLUSTER_CLASS = SpikeGPTCluster
    PERSON_CLASS = SpikeGPTPerson

    def set_project_up(self, team, user):
        super().set_project_up(team, user)

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
        from products.cohorts.backend.models.cohort import get_or_create_internal_test_users_cohort

        test_users_cohort = get_or_create_internal_test_users_cohort(team, initiating_user_email=user.email)
        team.test_account_filters = [
            {"key": "id", "type": "cohort", "value": test_users_cohort.pk, "operator": "not_in"},
        ]

        # Dashboard: LLM performance (project home)
        llm_dashboard = Dashboard.objects.create(
            team=team,
            name="LLM performance",
            description="How SpikeGPT's LLM pipeline performs across providers and tasks.",
            pinned=True,
        )
        team.primary_dashboard = llm_dashboard
        latency_heatmap_insight = Insight.objects.create(
            team=team,
            dashboard=llm_dashboard,
            saved=True,
            name="Average generation latency by provider and task",
            query=DataVisualizationNode(
                source=HogQLQuery(query=LATENCY_HEATMAP_SQL),
                display=ChartDisplayType.TWO_DIMENSIONAL_HEATMAP,
                chartSettings=ChartSettings(
                    heatmap=HeatmapSettings(
                        xAxisColumn="provider",
                        yAxisColumn="task",
                        valueColumn="avg_latency_s",
                        xAxisLabel="Provider",
                        yAxisLabel="Task",
                        gradientPreset="reds",
                        gradient=REDS_GRADIENT,
                        gradientScaleMode=GradientScaleMode.RELATIVE,
                    )
                ),
            ).model_dump(),
            last_modified_at=self.now - dt.timedelta(days=3),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=llm_dashboard,
            insight=latency_heatmap_insight,
            color="blue",
            layouts={
                "sm": {"h": 6, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
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
        cost_heatmap_insight = Insight.objects.create(
            team=team,
            dashboard=llm_dashboard,
            saved=True,
            name="LLM cost by provider and task",
            query=DataVisualizationNode(
                source=HogQLQuery(query=COST_HEATMAP_SQL),
                display=ChartDisplayType.TWO_DIMENSIONAL_HEATMAP,
                chartSettings=ChartSettings(
                    heatmap=HeatmapSettings(
                        xAxisColumn="provider",
                        yAxisColumn="task",
                        valueColumn="total_cost_usd",
                        xAxisLabel="Provider",
                        yAxisLabel="Task",
                        gradientPreset="blues",
                        gradient=BLUES_GRADIENT,
                        gradientScaleMode=GradientScaleMode.RELATIVE,
                    )
                ),
            ).model_dump(),
            last_modified_at=self.now - dt.timedelta(days=3),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=llm_dashboard,
            insight=cost_heatmap_insight,
            color="purple",
            layouts={
                "sm": {"h": 6, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
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
        generations_trend_insight = Insight.objects.create(
            team=team,
            dashboard=llm_dashboard,
            saved=True,
            name="Generations by provider",
            query=InsightVizNode(
                source=TrendsQuery(
                    series=[
                        EventsNode(
                            event="$ai_generation",
                            name="$ai_generation",
                        )
                    ],
                    trendsFilter=TrendsFilter(
                        display=ChartDisplayType.ACTIONS_LINE_GRAPH,
                    ),
                    breakdownFilter=BreakdownFilter(
                        breakdown_type=BreakdownType.EVENT,
                        breakdown="$ai_provider",
                    ),
                    interval=IntervalType.DAY,
                    dateRange=DateRange(
                        date_from="-30d",
                    ),
                )
            ).model_dump(),
            last_modified_at=self.now - dt.timedelta(days=3),
            last_modified_by=user,
        )
        DashboardTile.objects.create(
            dashboard=llm_dashboard,
            insight=generations_trend_insight,
            layouts={
                "sm": {"h": 5, "w": 12, "x": 0, "y": 6, "minH": 5, "minW": 3},
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
