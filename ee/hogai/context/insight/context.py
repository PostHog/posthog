from typing import Optional

from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.models import Team

from ee.hogai.chat_agent.query_executor.query_executor import execute_and_format_query
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.query import validate_assistant_query
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, AnyPydanticModelQuery


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
        name: str,
        description: str | None = None,
        insight_id: str | None = None,
        # Optional dashboard filter handling
        dashboard_filters: dict | None = None,
        filters_override: dict | None = None,
        variables_override: dict | None = None,
        # Customizable prompts
        schema_template: str | None = None,
        result_template: str | None = None,
    ):
        self.team = team
        self.query = query
        self.name = name
        self.description = description
        self.insight_id = insight_id
        self.dashboard_filters = dashboard_filters
        self.filters_override = filters_override
        self.variables_override = variables_override
        self.schema_template = schema_template
        self.result_template = result_template

    def _get_effective_query(self) -> AnyPydanticModelQuery | AnyAssistantGeneratedQuery:
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

    def format_schema(self) -> str:
        """Format insight as schema-only (no execution)."""
        if not self.schema_template:
            raise ValueError("schema_template must be provided to format schema")

        query_schema = self.query.model_dump_json(exclude_none=True)
        return format_prompt_string(
            self.schema_template,
            insight_name=self.name,
            insight_id=self.insight_id or "",
            description=self.description,
            query_type=self.query.kind,
            query_schema=query_schema,
        )

    async def aformat_results(self, insight_model_id: Optional[int] = None) -> str:
        """Execute query and format results."""
        if not self.result_template:
            raise ValueError("result_template must be provided to format results")

        effective_query = self._get_effective_query()

        results = await execute_and_format_query(
            self.team,
            effective_query,
            insight_id=insight_model_id,
        )

        return format_prompt_string(
            self.result_template,
            heading="",
            name=self.name,
            description=self.description,
            query_schema=self.query.model_dump_json(exclude_none=True),
            query=results,
            # Legacy fields for backward compatibility
            insight_name=self.name,
            insight_id=self.insight_id or "",
            results=results,
        )
