from typing import Optional, cast

from langchain_core.prompts import PromptTemplate
from posthoganalytics import capture_exception

from ee.hogai.graph.query_executor.query_executor import AssistantQueryExecutor, SupportedQueryTypes

# Import moved inside functions to avoid circular imports
from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.schema import (
    FunnelsQuery,
    HogQLQuery,
    MaxUIContext,
    MaxInsightContext,
    RetentionQuery,
    TrendsQuery,
)

from ...base import AssistantNode
from ..prompts import (
    ROOT_DASHBOARD_CONTEXT_PROMPT,
    ROOT_DASHBOARDS_CONTEXT_PROMPT,
    ROOT_INSIGHT_CONTEXT_PROMPT,
    ROOT_INSIGHTS_CONTEXT_PROMPT,
    ROOT_UI_CONTEXT_PROMPT,
)

# Map query kinds to their respective full UI query classes
# NOTE: Update this and SupportedQueryTypes when adding new query types
MAX_SUPPORTED_QUERY_KIND_TO_MODEL: dict[str, type[SupportedQueryTypes]] = {
    "TrendsQuery": TrendsQuery,
    "FunnelsQuery": FunnelsQuery,
    "RetentionQuery": RetentionQuery,
    "HogQLQuery": HogQLQuery,
}


class UIContextNodeMixin(AssistantNode):
    """Mixin that provides UI context formatting capabilities for root nodes."""

    def _format_ui_context(self, ui_context: Optional[MaxUIContext]) -> str:
        """
        Format UI context into template variables for the prompt.

        Args:
            ui_context: UI context data or None

        Returns:
            Dict of context variables for prompt template
        """
        if not ui_context:
            return ""

        query_runner = AssistantQueryExecutor(self._team, self._utc_now_datetime)

        # Extract global filters and variables override from UI context
        filters_override = ui_context.filters_override.model_dump() if ui_context.filters_override else None
        variables_override = ui_context.variables_override if ui_context.variables_override else None

        # Format dashboard context with insights
        dashboard_context = ""
        if ui_context.dashboards:
            dashboard_contexts = []

            for dashboard in ui_context.dashboards:
                dashboard_insights = ""
                if dashboard.insights:
                    insight_texts = []
                    for insight in dashboard.insights:
                        # Get formatted insight
                        dashboard_filters = (
                            dashboard.filters.model_dump()
                            if hasattr(dashboard, "filters") and dashboard.filters
                            else None
                        )
                        formatted_insight = self._run_and_format_insight(
                            insight,
                            query_runner,
                            dashboard_filters,
                            filters_override,
                            variables_override,
                            heading="####",
                        )
                        if formatted_insight:
                            insight_texts.append(formatted_insight)

                    dashboard_insights = "\n\n".join(insight_texts)

                # Use the dashboard template
                dashboard_text = (
                    PromptTemplate.from_template(ROOT_DASHBOARD_CONTEXT_PROMPT, template_format="mustache")
                    .format_prompt(
                        name=dashboard.name or f"Dashboard {dashboard.id}",
                        description=dashboard.description if dashboard.description else None,
                        insights=dashboard_insights,
                    )
                    .to_string()
                )
                dashboard_contexts.append(dashboard_text)

            if dashboard_contexts:
                joined_dashboards = "\n\n".join(dashboard_contexts)
                # Use the dashboards template
                dashboard_context = (
                    PromptTemplate.from_template(ROOT_DASHBOARDS_CONTEXT_PROMPT, template_format="mustache")
                    .format_prompt(dashboards=joined_dashboards)
                    .to_string()
                )

        # Format standalone insights context
        insights_context = ""
        if ui_context.insights:
            insights_results = []
            for insight in ui_context.insights:
                result = self._run_and_format_insight(
                    insight, query_runner, None, filters_override, variables_override, heading="##"
                )
                if result:
                    insights_results.append(result)

            if insights_results:
                joined_results = "\n\n".join(insights_results)
                # Use the insights template
                insights_context = (
                    PromptTemplate.from_template(ROOT_INSIGHTS_CONTEXT_PROMPT, template_format="mustache")
                    .format_prompt(insights=joined_results)
                    .to_string()
                )

        # Format events and actions context
        events_context = self._format_entity_context(ui_context.events, "events", "Event")
        actions_context = self._format_entity_context(ui_context.actions, "actions", "Action")

        if dashboard_context or insights_context or events_context or actions_context:
            return self._render_user_context_template(
                dashboard_context, insights_context, events_context, actions_context
            )
        return ""

    def _run_and_format_insight(
        self,
        insight: MaxInsightContext,
        query_runner: AssistantQueryExecutor,
        dashboard_filters: Optional[dict] = None,
        filters_override: Optional[dict] = None,
        variables_override: Optional[dict] = None,
        heading: Optional[str] = None,
    ) -> str | None:
        """
        Run and format a single insight for AI consumption.

        Args:
            insight: Insight object with query and metadata
            query_runner: AssistantQueryExecutor instance for execution
            dashboard_filters: Optional dashboard filters to apply to the query

        Returns:
            Formatted insight string or empty string if failed
        """
        try:
            query_kind = cast(str | None, getattr(insight.query, "kind", None))
            serialized_query = insight.query.model_dump_json(exclude_none=True)

            if not query_kind or query_kind not in MAX_SUPPORTED_QUERY_KIND_TO_MODEL:
                return None  # Skip unsupported query types

            query_obj = cast(SupportedQueryTypes, insight.query)

            if dashboard_filters or filters_override or variables_override:
                query_dict = insight.query.model_dump(mode="json")
                if dashboard_filters:
                    query_dict = apply_dashboard_filters_to_dict(query_dict, dashboard_filters, self._team)
                if filters_override:
                    query_dict = apply_dashboard_filters_to_dict(query_dict, filters_override, self._team)
                if variables_override:
                    query_dict = apply_dashboard_variables_to_dict(query_dict, variables_override, self._team)

                QueryModel = MAX_SUPPORTED_QUERY_KIND_TO_MODEL[query_kind]
                query_obj = QueryModel.model_validate(query_dict)

            raw_results, _ = query_runner.run_and_format_query(query_obj)

            result = (
                PromptTemplate.from_template(ROOT_INSIGHT_CONTEXT_PROMPT, template_format="mustache")
                .format_prompt(
                    heading=heading or "",
                    name=insight.name or f"ID {insight.id}",
                    description=insight.description,
                    query_schema=serialized_query,
                    query=raw_results,
                )
                .to_string()
            )
            return result

        except Exception:
            # Skip insights that fail to run
            capture_exception()
            return None

    def _format_entity_context(self, entities, context_tag: str, entity_type: str) -> str:
        """
        Format entity context (events or actions) into XML context string.

        Args:
            entities: List of entities (events or actions) or None
            context_tag: XML tag name (e.g., "events" or "actions")
            entity_type: Entity type for display (e.g., "Event" or "Action")

        Returns:
            Formatted context string or empty string if no entities
        """
        if not entities:
            return ""

        entity_details = []
        for entity in entities:
            name = entity.name or f"{entity_type} {entity.id}"
            entity_detail = f'"{name}'
            if entity.description:
                entity_detail += f": {entity.description}"
            entity_detail += '"'
            entity_details.append(entity_detail)

        if entity_details:
            return f"<{context_tag}_context>{entity_type} names the user is referring to:\n{', '.join(entity_details)}\n</{context_tag}_context>"
        return ""

    def _render_user_context_template(
        self, dashboard_context: str, insights_context: str, events_context: str, actions_context: str
    ) -> str:
        """Render the user context template with the provided context strings."""
        template = PromptTemplate.from_template(ROOT_UI_CONTEXT_PROMPT, template_format="mustache")
        return template.format_prompt(
            ui_context_dashboard=dashboard_context,
            ui_context_insights=insights_context,
            ui_context_events=events_context,
            ui_context_actions=actions_context,
        ).to_string()
