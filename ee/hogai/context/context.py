import asyncio
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Optional, cast
from uuid import uuid4

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import (
    AgentMode,
    ContextMessage,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    MaxBillingContext,
    MaxInsightContext,
    MaxUIContext,
    RetentionQuery,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsTopCustomersQuery,
    TrendsQuery,
)

from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.graph.query_executor.query_executor import AssistantQueryExecutor, SupportedQueryTypes
from ee.hogai.utils.helpers import find_start_message, find_start_message_idx, insert_messages_before_start
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AnyAssistantSupportedQuery, AssistantMessageUnion, BaseStateWithMessages

from .prompts import (
    CONTEXT_MODE_PROMPT,
    CONTEXTUAL_TOOLS_REMINDER_PROMPT,
    ROOT_DASHBOARD_CONTEXT_PROMPT,
    ROOT_DASHBOARDS_CONTEXT_PROMPT,
    ROOT_INSIGHT_CONTEXT_PROMPT,
    ROOT_INSIGHTS_CONTEXT_PROMPT,
    ROOT_UI_CONTEXT_PROMPT,
)

# Build mapping of query kind names to their model classes for validation
# Use the 'kind' field value (e.g., "TrendsQuery") as the key
# NOTE: This needs to be kept in sync with the schema
SUPPORTED_QUERY_MODEL_BY_KIND: dict[str, type[AnyAssistantSupportedQuery]] = {
    "TrendsQuery": TrendsQuery,
    "FunnelsQuery": FunnelsQuery,
    "RetentionQuery": RetentionQuery,
    "HogQLQuery": HogQLQuery,
    "RevenueAnalyticsGrossRevenueQuery": RevenueAnalyticsGrossRevenueQuery,
    "RevenueAnalyticsMetricsQuery": RevenueAnalyticsMetricsQuery,
    "RevenueAnalyticsMRRQuery": RevenueAnalyticsMRRQuery,
    "RevenueAnalyticsTopCustomersQuery": RevenueAnalyticsTopCustomersQuery,
}


class AssistantContextManager(AssistantContextMixin):
    """Manager that provides context formatting capabilities."""

    def __init__(self, team: Team, user: User, config: RunnableConfig | None = None):
        self._team = team
        self._user = user
        self._config = config or {}

    async def get_state_messages_with_context(
        self, state: BaseStateWithMessages
    ) -> Sequence[AssistantMessageUnion] | None:
        """
        Returns the state messages with context messages injected. If no context prompts should be added, returns None.
        """
        if context_prompts := await self._get_context_prompts(state):
            # Insert context messages BEFORE the start human message, so they're properly cached and the context is retained.
            updated_messages = self._inject_context_messages(state, context_prompts)
            return updated_messages
        return None

    def get_ui_context(self, state: BaseStateWithMessages) -> MaxUIContext | None:
        """
        Extracts the UI context from the latest human message.
        """
        message = find_start_message(state.messages)
        if isinstance(message, HumanMessage) and message.ui_context is not None:
            return message.ui_context
        return None

    def has_awaitable_context(self, state: BaseStateWithMessages) -> bool:
        ui_context = self.get_ui_context(state)
        if ui_context and (ui_context.dashboards or ui_context.insights):
            return True
        return False

    def get_contextual_tools(self) -> dict[str, dict[str, Any]]:
        """
        Extracts contextual tools from the runnable config, returning a mapping of available contextual tool names to context.
        """
        contextual_tools = (self._config.get("configurable") or {}).get("contextual_tools") or {}
        if not isinstance(contextual_tools, dict):
            return {}

        return contextual_tools

    def get_billing_context(self) -> MaxBillingContext | None:
        """
        Extracts the billing context from the runnable config.
        """
        billing_context = (self._config.get("configurable") or {}).get("billing_context")
        if not billing_context:
            return None
        return MaxBillingContext.model_validate(billing_context)

    @database_sync_to_async
    def check_user_has_billing_access(self) -> bool:
        """
        Check if the user has access to the billing tool.
        """
        return self._user.organization_memberships.get(organization=self._team.organization).level in (
            OrganizationMembership.Level.ADMIN,
            OrganizationMembership.Level.OWNER,
        )

    def get_groups(self):
        """
        Returns the ORM chain of the team's groups.
        """
        return GroupTypeMapping.objects.filter(project_id=self._team.project_id).order_by("group_type_index")

    @lru_cache(maxsize=1)
    async def get_group_names(self) -> list[str]:
        """
        Returns the names of the team's groups.
        """
        return [group async for group in self.get_groups().values_list("group_type", flat=True)]

    async def _format_ui_context(self, ui_context: MaxUIContext | None) -> str | None:
        """
        Format UI context into template variables for the prompt.

        Args:
            ui_context: UI context data or None

        Returns:
            Dict of context variables for prompt template
        """
        if not ui_context:
            return None

        query_runner = AssistantQueryExecutor(self._team, self._utc_now_datetime)

        # Collect all unique insights with their contexts
        insight_map: dict[str, tuple[MaxInsightContext, Optional[dict], str]] = {}

        # Collect insights from dashboards
        dashboard_insights_mapping: dict[str, list[str]] = {}  # dashboard_id -> list of insight_ids
        if ui_context.dashboards:
            for dashboard in ui_context.dashboards:
                if dashboard.insights:
                    dashboard_id = str(dashboard.id) if dashboard.id else dashboard.name or ""
                    dashboard_insights_mapping[dashboard_id] = []
                    dashboard_filters = (
                        dashboard.filters.model_dump() if hasattr(dashboard, "filters") and dashboard.filters else None
                    )
                    for insight in dashboard.insights:
                        # Create unique key for deduplication
                        # Use hash of dashboard_filters for the key to avoid issues with dict-to-string conversion
                        filters_hash = str(hash(str(dashboard_filters))) if dashboard_filters else "None"
                        insight_key = f"{insight.id or ''}-{filters_hash}-####"
                        if insight_key not in insight_map:
                            insight_map[insight_key] = (insight, dashboard_filters, "####")
                        dashboard_insights_mapping[dashboard_id].append(insight_key)

        # Collect standalone insights
        standalone_insight_keys = []
        if ui_context.insights:
            for insight in ui_context.insights:
                insight_key = f"{insight.id or ''}-None-##"
                if insight_key not in insight_map:
                    insight_map[insight_key] = (insight, None, "##")
                standalone_insight_keys.append(insight_key)

        # Run all unique insights in parallel
        insight_results_map: dict[str, str | None] = {}
        if insight_map:
            insight_tasks = [
                self._arun_and_format_insight(insight, query_runner, filters, heading)
                for insight, filters, heading in insight_map.values()
            ]
            insight_keys = list(insight_map.keys())

            insight_results = await asyncio.gather(*insight_tasks, return_exceptions=True)

            # Map results back to keys
            for key, result in zip(insight_keys, insight_results):
                if result is not None and not isinstance(result, Exception):
                    insight_results_map[key] = cast(str, result)
                else:
                    if isinstance(result, Exception):
                        # Log the exception for debugging while still allowing other insights to process
                        capture_exception(
                            result,
                            distinct_id=self._get_user_distinct_id(self._config),
                            properties={**self._get_debug_props(self._config), "insight_key": key},
                        )
                    insight_results_map[key] = None

        # Build dashboard context using the results
        dashboard_context = ""
        if ui_context.dashboards and dashboard_insights_mapping:
            dashboard_contexts = []
            for dashboard in ui_context.dashboards:
                dashboard_id = str(dashboard.id) if dashboard.id else dashboard.name or ""
                if dashboard_id in dashboard_insights_mapping:
                    insight_keys = dashboard_insights_mapping[dashboard_id]
                    insight_texts: list[str] = [
                        cast(str, insight_results_map[key])
                        for key in insight_keys
                        if insight_results_map.get(key) is not None
                    ]
                    dashboard_insights = "\n\n".join(insight_texts) if insight_texts else ""
                else:
                    dashboard_insights = ""

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
                dashboard_context = (
                    PromptTemplate.from_template(ROOT_DASHBOARDS_CONTEXT_PROMPT, template_format="mustache")
                    .format_prompt(dashboards=joined_dashboards)
                    .to_string()
                )

        # Build standalone insights context using the results
        insights_context = ""
        if standalone_insight_keys:
            insights_results: list[str] = [
                cast(str, insight_results_map[key])
                for key in standalone_insight_keys
                if insight_results_map.get(key) is not None
            ]

            if insights_results:
                joined_results = "\n\n".join(insights_results)
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
        return None

    async def _arun_and_format_insight(
        self,
        insight: MaxInsightContext,
        query_runner: AssistantQueryExecutor,
        dashboard_filters: Optional[dict] = None,
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

            if not query_kind or query_kind not in SUPPORTED_QUERY_MODEL_BY_KIND.keys():
                return None  # Skip unsupported query types

            query_obj = cast(SupportedQueryTypes, insight.query)

            if dashboard_filters or insight.filtersOverride or insight.variablesOverride:
                query_dict = insight.query.model_dump(mode="json")
                if dashboard_filters:
                    query_dict = apply_dashboard_filters_to_dict(query_dict, dashboard_filters, self._team)
                if insight.filtersOverride:
                    query_dict = apply_dashboard_filters_to_dict(
                        query_dict, insight.filtersOverride.model_dump(mode="json"), self._team
                    )
                if insight.variablesOverride:
                    variables_overrides = {k: v.model_dump(mode="json") for k, v in insight.variablesOverride.items()}
                    query_dict = apply_dashboard_variables_to_dict(query_dict, variables_overrides, self._team)

                if query_kind not in SUPPORTED_QUERY_MODEL_BY_KIND:
                    return None  # Skip if query kind is not supported after filters applied
                QueryModel = SUPPORTED_QUERY_MODEL_BY_KIND[query_kind]
                query_obj = QueryModel.model_validate(query_dict)

            raw_results, _ = await query_runner.arun_and_format_query(query_obj)

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

        except Exception as err:
            # Skip insights that fail to run
            capture_exception(
                err,
                distinct_id=self._get_user_distinct_id(self._config),
                properties=self._get_debug_props(self._config),
            )
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

    async def _get_context_prompts(self, state: BaseStateWithMessages) -> list[str]:
        prompts: list[str] = []
        if find_start_message_idx(state.messages, state.start_id) == 0 and (
            mode_prompt := self._get_mode_prompt(state.agent_mode)
        ):
            prompts.append(mode_prompt)
        if contextual_tools := self._get_contextual_tools_prompt():
            prompts.append(contextual_tools)
        if ui_context := await self._format_ui_context(self.get_ui_context(state)):
            prompts.append(ui_context)
        return self._deduplicate_context_messages(state, prompts)

    def _get_contextual_tools_prompt(self) -> str | None:
        from ee.hogai.registry import get_contextual_tool_class

        contextual_tools_prompt = [
            f"<{tool_name}>\n"
            f"{get_contextual_tool_class(tool_name)(team=self._team, user=self._user).format_context_prompt_injection(tool_context)}\n"  # type: ignore
            f"</{tool_name}>"
            for tool_name, tool_context in self.get_contextual_tools().items()
            if get_contextual_tool_class(tool_name) is not None
        ]
        if contextual_tools_prompt:
            tools = "\n".join(contextual_tools_prompt)
            return CONTEXTUAL_TOOLS_REMINDER_PROMPT.format(tools=tools)
        return None

    def _deduplicate_context_messages(self, state: BaseStateWithMessages, context_prompts: list[str]) -> list[str]:
        """Naive deduplication of context messages by content."""
        human_messages = {message.content for message in state.messages if isinstance(message, ContextMessage)}
        return [prompt for prompt in context_prompts if prompt not in human_messages]

    def _inject_context_messages(
        self, state: BaseStateWithMessages, context_prompts: list[str]
    ) -> list[AssistantMessageUnion]:
        context_messages = [ContextMessage(content=prompt, id=str(uuid4())) for prompt in context_prompts]
        # Insert context messages right before the start message
        return insert_messages_before_start(state.messages, context_messages, start_id=state.start_id)

    def _get_mode_prompt(self, mode: AgentMode | None) -> str:
        return format_prompt_string(CONTEXT_MODE_PROMPT, mode=mode.value if mode else AgentMode.PRODUCT_ANALYTICS.value)
