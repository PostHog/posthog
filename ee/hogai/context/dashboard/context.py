import asyncio
from collections.abc import Sequence
from typing import Generic

from pydantic import BaseModel

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from ee.hogai.context.insight.context import InsightContext
from ee.hogai.utils.helpers import build_dashboard_url
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AnyPydanticModelQuery

from .prompts import DASHBOARD_RESULT_TEMPLATE


class DashboardInsightContext(BaseModel, Generic[AnyPydanticModelQuery]):
    """Normalization for dashboard insights: data might come from the UI context, an insight model, or an artifact."""

    query: AnyPydanticModelQuery
    name: str | None = None
    description: str | None = None
    short_id: str | None = None
    db_id: int | None = None
    filters_override: dict | None = None
    variables_override: dict | None = None
    layout: dict | None = None


class DashboardContext:
    """
    Formatter class for dashboard context used across the assistant.

    Accepts raw insight data and creates InsightContext objects internally.
    Provides methods to format schema or execute all insights in parallel and format results.
    """

    def __init__(
        self,
        team: Team,
        insights_data: Sequence[DashboardInsightContext],
        name: str | None = None,
        description: str | None = None,
        dashboard_id: str | None = None,
        dashboard_filters: dict | None = None,
        max_concurrent_queries: int = 5,
    ):
        """
        Initialize DashboardContext.

        Args:
            team: Team instance
            insights_data: List of DashboardInsightContext models containing insight query and metadata
            name: Dashboard name
            description: Dashboard description
            dashboard_id: Dashboard ID
            dashboard_filters: Dashboard-level filters to apply to all insights
            max_concurrent_queries: Max concurrent insight queries (default: 5)
        """
        self.team = team
        self.name = name
        self.description = description
        self.dashboard_id = dashboard_id
        self.dashboard_url = build_dashboard_url(team, int(dashboard_id)) if dashboard_id else None
        self.dashboard_filters = dashboard_filters
        self._semaphore = asyncio.Semaphore(max_concurrent_queries)

        # Sort by layout position and create InsightContext objects
        sorted_data = self.sort_by_layout(insights_data)
        self.insights = [self._create_insight_context(data) for data in sorted_data]

    @staticmethod
    def sort_by_layout(
        insights_data: Sequence[DashboardInsightContext], layout_size: str = "sm"
    ) -> list[DashboardInsightContext]:
        """Sort insights by their layout position (y, then x)."""
        return sorted(
            insights_data,
            key=lambda i: (
                (i.layout or {}).get(layout_size, {}).get("y", 100),
                (i.layout or {}).get(layout_size, {}).get("x", 100),
            ),
        )

    async def execute_and_format(self, prompt_template: str = DASHBOARD_RESULT_TEMPLATE) -> str:
        """Execute all insight queries in parallel and format combined results."""
        if not self.insights:
            return format_prompt_string(
                prompt_template,
                dashboard_name=self.name or "Dashboard",
                dashboard_id=self.dashboard_id,
                dashboard_url=self.dashboard_url,
                description=self.description,
                insights="",
            )

        # return_exceptions=True keeps one failing insight from dropping the whole dashboard.
        insight_tasks = [self._execute_insight_with_semaphore(insight) for insight in self.insights]
        insight_results = await asyncio.gather(*insight_tasks, return_exceptions=True)
        formatted_insights = self._resolve_insight_results(insight_results, "Error preparing insight context.")

        return format_prompt_string(
            prompt_template,
            dashboard_name=self.name or "Dashboard",
            dashboard_id=self.dashboard_id,
            dashboard_url=self.dashboard_url,
            description=self.description,
            insights="\n\n".join(formatted_insights),
        )

    async def format_schema(self, prompt_template: str = DASHBOARD_RESULT_TEMPLATE) -> str:
        """Format all insight schemas without execution."""
        if not self.insights:
            return format_prompt_string(
                prompt_template,
                dashboard_name=self.name or "Dashboard",
                dashboard_id=self.dashboard_id,
                dashboard_url=self.dashboard_url,
                description=self.description,
            )

        # No semaphore (unlike execute_and_format): schema formatting runs no queries, so there's
        # no DB load to bound. return_exceptions=True keeps one failure from dropping the dashboard.
        schema_results = await asyncio.gather(
            *(insight.format_schema() for insight in self.insights), return_exceptions=True
        )
        insight_schemas = self._resolve_insight_results(schema_results, "Error preparing insight schema.")

        return format_prompt_string(
            prompt_template,
            name=self.name or "Dashboard",
            dashboard_name=self.name or "Dashboard",
            dashboard_id=self.dashboard_id,
            dashboard_url=self.dashboard_url,
            description=self.description,
            insights="\n\n".join(insight_schemas),
        )

    def _resolve_insight_results(self, results: Sequence[str | BaseException], error_message: str) -> list[str]:
        """Map gathered per-insight results to strings so one failure can't drop the dashboard.

        Cancellation is re-raised (never swallowed); any other exception is captured and
        replaced with a short placeholder.
        """
        formatted: list[str] = []
        for insight, result in zip(self.insights, results):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                capture_exception(result)
                formatted.append(f'Insight "{insight.name or "Insight"}": {error_message}')
            else:
                formatted.append(result)
        return formatted

    async def _execute_insight_with_semaphore(self, insight: InsightContext) -> str:
        """Execute a single insight with semaphore control."""
        async with self._semaphore:
            return await insight.execute_and_format(return_exceptions=True)

    def _create_insight_context(self, data: DashboardInsightContext) -> InsightContext:
        """Create an InsightContext from DashboardInsightContext model."""
        return InsightContext(
            team=self.team,
            query=data.query,
            name=data.name,
            description=data.description,
            insight_id=data.short_id,
            insight_model_id=data.db_id,
            insight_short_id=data.short_id,
            dashboard_filters=self.dashboard_filters,
            filters_override=data.filters_override,
            variables_override=data.variables_override,
        )
