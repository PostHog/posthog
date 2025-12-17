import asyncio
from collections.abc import Sequence

from posthoganalytics import capture_exception
from pydantic import BaseModel

from posthog.models import Team

from ee.hogai.context.insight.context import InsightContext
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AnyPydanticModelQuery

from .prompts import DASHBOARD_RESULT_TEMPLATE


class InsightData(BaseModel):
    """Data structure for creating an InsightContext within a dashboard."""

    query: AnyPydanticModelQuery
    name: str | None = None
    description: str | None = None
    insight_id: str | None = None


class DashboardContext:
    """
    Formatter class for dashboard context used across the assistant.

    Accepts raw insight data and creates InsightContext objects internally.
    Provides methods to format schema or execute all insights in parallel and format results.
    """

    def __init__(
        self,
        team: Team,
        insights_data: Sequence[InsightData],
        name: str | None = None,
        description: str | None = None,
        dashboard_id: str | None = None,
        dashboard_filters: dict | None = None,
        filters_override: dict | None = None,
        variables_override: dict | None = None,
        max_concurrent_queries: int = 3,
    ):
        """
        Initialize DashboardContext.

        Args:
            team: Team instance
            insights_data: List of InsightData models containing insight query and metadata
            name: Dashboard name
            description: Dashboard description
            dashboard_id: Dashboard ID
            dashboard_filters: Dashboard-level filters to apply to all insights
            filters_override: Dashboard-level filter overrides to apply to all insights
            variables_override: Dashboard-level variable overrides to apply to all insights
            max_concurrent_queries: Max concurrent insight queries
        """
        self.team = team
        self.name = name
        self.description = description
        self.dashboard_id = dashboard_id
        self.dashboard_filters = dashboard_filters
        self.filters_override = filters_override
        self.variables_override = variables_override
        self._semaphore = asyncio.Semaphore(max_concurrent_queries)

        # Create InsightContext objects from InsightData models
        self.insights = [self._create_insight_context(data) for data in insights_data]

    def _create_insight_context(self, data: InsightData) -> InsightContext:
        """Create an InsightContext from InsightData model."""
        return InsightContext(
            team=self.team,
            query=data.query,
            name=data.name,
            description=data.description,
            insight_id=data.insight_id,
            dashboard_filters=self.dashboard_filters,
            filters_override=self.filters_override,
            variables_override=self.variables_override,
        )

    async def execute(self, prompt_template: str = DASHBOARD_RESULT_TEMPLATE) -> str:
        """Execute all insight queries in parallel and format combined results."""
        if not self.insights:
            return format_prompt_string(
                prompt_template,
                name=self.name or "Dashboard",  # For ROOT_DASHBOARD_CONTEXT_PROMPT
                dashboard_name=self.name or "Dashboard",  # For DASHBOARD_RESULT_TEMPLATE
                dashboard_id=self.dashboard_id,
                description=self.description,
                insights="",
            )

        # Run all insights in parallel with semaphore control
        insight_tasks = [self._execute_insight_with_semaphore(insight) for insight in self.insights]
        insight_results = await asyncio.gather(*insight_tasks, return_exceptions=True)

        # Filter out failed results
        valid_results = [
            result for result in insight_results if result is not None and not isinstance(result, Exception)
        ]

        insights_text = "\n\n".join(valid_results) if valid_results else ""

        return format_prompt_string(
            prompt_template,
            name=self.name or "Dashboard",  # For ROOT_DASHBOARD_CONTEXT_PROMPT
            dashboard_name=self.name or "Dashboard",  # For DASHBOARD_RESULT_TEMPLATE
            dashboard_id=self.dashboard_id,
            description=self.description,
            insights=insights_text,
        )

    def format_schema(self, prompt_template: str = DASHBOARD_RESULT_TEMPLATE) -> str:
        """Format all insight schemas without execution."""
        if not self.insights:
            return format_prompt_string(
                prompt_template,
                name=self.name or "Dashboard",  # For ROOT_DASHBOARD_CONTEXT_PROMPT
                dashboard_name=self.name or "Dashboard",  # For DASHBOARD_RESULT_TEMPLATE
                dashboard_id=self.dashboard_id,
                description=self.description,
                insights="",
            )

        insight_schemas = []
        for insight in self.insights:
            try:
                schema = insight.format_schema()
                insight_schemas.append(schema)
            except Exception as e:
                # Log but continue processing other insights
                capture_exception(e)
                continue

        insights_text = "\n\n".join(insight_schemas) if insight_schemas else ""

        return format_prompt_string(
            prompt_template,
            name=self.name or "Dashboard",  # For ROOT_DASHBOARD_CONTEXT_PROMPT
            dashboard_name=self.name or "Dashboard",  # For DASHBOARD_RESULT_TEMPLATE
            dashboard_id=self.dashboard_id,
            description=self.description,
            insights=insights_text,
        )

    async def _execute_insight_with_semaphore(self, insight: InsightContext) -> str | None:
        """Execute a single insight with semaphore control."""
        async with self._semaphore:
            try:
                return await insight.execute()
            except Exception as e:
                # Log but don't fail the entire dashboard
                capture_exception(e)
                return None
