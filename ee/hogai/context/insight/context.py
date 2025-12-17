from typing import Optional

from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.models import Team

from ee.hogai.context.insight.query_executor import execute_and_format_query
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.query import validate_assistant_query
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, AnyPydanticModelQuery

from .prompts import INSIGHT_RESULT_TEMPLATE


class InsightContext:
    """
    Formatter class for insight context used across the assistant.

    Accepts insight data directly and provides methods to format schema or execute and format results.
    Supports optional dashboard filter/variable overrides before execution.
    """

    def __init__(
        self,
        team: Team,
        query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery,
        name: str | None = None,
        description: str | None = None,
        insight_id: str | None = None,
        # Optional dashboard filter handling
        dashboard_filters: dict | None = None,
        filters_override: dict | None = None,
        variables_override: dict | None = None,
    ):
        self.team = team
        self.query = query
        self.name = name
        self.description = description
        self.insight_id = insight_id
        self.dashboard_filters = dashboard_filters
        self.filters_override = filters_override
        self.variables_override = variables_override

    async def execute(
        self, prompt_template: str = INSIGHT_RESULT_TEMPLATE, insight_model_id: Optional[int] = None
    ) -> str:
        """Execute query and format results."""
        effective_query = self._get_effective_query()
        query_schema = effective_query.model_dump_json(exclude_none=True)

        try:
            results = await execute_and_format_query(
                self.team,
                effective_query,
                insight_id=insight_model_id,
            )
        except Exception as e:
            raise MaxToolRetryableError(f"Error executing query: {str(e)}")

        return format_prompt_string(
            prompt_template,
            insight_name=self.name or "Insight",
            insight_id=self.insight_id,
            insight_description=self.description,
            query_schema=query_schema,
            results=results,
        )

    def format_schema(self, prompt_template: str = INSIGHT_RESULT_TEMPLATE) -> str:
        """Format insight as schema-only (no execution)."""
        effective_query = self._get_effective_query()
        query_schema = effective_query.model_dump_json(exclude_none=True)
        return format_prompt_string(
            prompt_template,
            insight_name=self.name,
            insight_id=self.insight_id or "",
            insight_description=self.description,
            query_schema=query_schema,
        )

    def _get_effective_query(self):
        """Apply dashboard filters/overrides if provided."""
        if not (self.dashboard_filters or self.filters_override or self.variables_override):
            return self.query

        query_dict = self.query.model_dump(mode="json")

        if self.dashboard_filters:
            query_dict = apply_dashboard_filters_to_dict(query_dict, self.dashboard_filters, self.team)

        if self.filters_override:
            query_dict = apply_dashboard_filters_to_dict(query_dict, self.filters_override, self.team)

        if self.variables_override:
            query_dict = apply_dashboard_variables_to_dict(query_dict, self.variables_override, self.team)

        return validate_assistant_query(query_dict)
