import asyncio
from collections.abc import Sequence
from functools import cached_property
from typing import Any, Optional, cast
from uuid import uuid4

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantTool,
    ContextMessage,
    HumanMessage,
    MaxBillingContext,
    MaxInsightContext,
    MaxUIContext,
    ModeContext,
)

from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.helpers import find_start_message, find_start_message_idx, insert_messages_before_start
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantMessageUnion, BaseStateWithMessages

from .prompts import (
    CONTEXT_INITIAL_MODE_PROMPT,
    CONTEXT_MODE_PROMPT,
    CONTEXT_MODE_SWITCH_PROMPT,
    CONTEXTUAL_TOOLS_REMINDER_PROMPT,
    ROOT_DASHBOARD_CONTEXT_PROMPT,
    ROOT_DASHBOARDS_CONTEXT_PROMPT,
    ROOT_INSIGHT_CONTEXT_PROMPT,
    ROOT_INSIGHTS_CONTEXT_PROMPT,
    ROOT_UI_CONTEXT_PROMPT,
)


class AssistantContextManager(AssistantContextMixin):
    """Manager that provides context formatting capabilities."""

    def __init__(self, team: Team, user: User, config: RunnableConfig | None = None):
        self._team = team
        self._user = user
        self._config = config or {}
        self._artifact_manager = ArtifactManager(self._team, self._user, self._config)

    @cached_property
    def artifacts(self) -> ArtifactManager:
        """
        Returns the artifact manager for the team.

        Exposed through .artifacts for easy access to artifact manager from nodes.
        """
        return self._artifact_manager

    async def get_state_messages_with_context(
        self, state: BaseStateWithMessages
    ) -> Sequence[AssistantMessageUnion] | None:
        """
        Returns the state messages with context messages injected. If no context prompts should be added, returns None.
        """
        if context_prompts := await self._get_context_messages(state):
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

        # Build dashboard contexts
        dashboard_context = ""
        if ui_context.dashboards:
            dashboard_contexts = []
            for dashboard in ui_context.dashboards:
                dashboard_filters = (
                    dashboard.filters.model_dump(exclude_none=True)
                    if hasattr(dashboard, "filters") and dashboard.filters
                    else None
                )

                # Build DashboardInsightContext models for this dashboard
                insights_data: list[DashboardInsightContext] = []
                for insight in dashboard.insights:
                    filters_override = (
                        insight.filtersOverride.model_dump(mode="json") if insight.filtersOverride else None
                    )
                    variables_override = (
                        {k: v.model_dump(mode="json") for k, v in insight.variablesOverride.items()}
                        if insight.variablesOverride
                        else None
                    )
                    insights_data.append(
                        DashboardInsightContext(
                            query=insight.query,
                            name=insight.name,
                            description=insight.description,
                            short_id=insight.id,
                            filters_override=filters_override,
                            variables_override=variables_override,
                        )
                    )

                # Create DashboardContext and execute
                dashboard_ctx = DashboardContext(
                    team=self._team,
                    insights_data=insights_data,
                    name=dashboard.name or f"Dashboard {dashboard.id}",
                    description=dashboard.description,
                    dashboard_id=str(dashboard.id) if dashboard.id else None,
                    dashboard_filters=dashboard_filters,
                )

                try:
                    dashboard_text = await dashboard_ctx.execute_and_format()
                    dashboard_contexts.append(
                        format_prompt_string(ROOT_DASHBOARD_CONTEXT_PROMPT, content=dashboard_text)
                    )
                except Exception as e:
                    capture_exception(
                        e,
                        distinct_id=self._get_user_distinct_id(self._config),
                        properties=self._get_debug_props(self._config),
                    )
                    continue

            if dashboard_contexts:
                joined_dashboards = "\n\n".join(dashboard_contexts)
                dashboard_context = (
                    PromptTemplate.from_template(ROOT_DASHBOARDS_CONTEXT_PROMPT, template_format="mustache")
                    .format_prompt(dashboards=joined_dashboards)
                    .to_string()
                )

        # Build standalone insights context
        insights_context = ""
        if ui_context.insights:
            insight_contexts = [self._build_insight_context(insight) for insight in ui_context.insights]

            # Execute all standalone insights in parallel
            insight_tasks = [self._execute_and_format_insight(ctx) for ctx in insight_contexts]
            insight_results = await asyncio.gather(*insight_tasks, return_exceptions=True)

            # Filter out failed results
            insights_results: list[str] = [
                cast(str, result)
                for result in insight_results
                if result is not None and not isinstance(result, Exception) and result
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

    def _build_insight_context(
        self,
        insight: MaxInsightContext,
        dashboard_filters: Optional[dict] = None,
    ) -> InsightContext:
        """
        Build an InsightContext from MaxInsightContext data.

        Args:
            insight: Insight object with query and metadata
            dashboard_filters: Optional dashboard filters to apply to the query

        Returns:
            InsightContext instance
        """
        # Convert filters_override to dict if needed
        filters_override = None
        if insight.filtersOverride:
            filters_override = insight.filtersOverride.model_dump(mode="json")

        # Convert variables_override to dict if needed
        variables_override = None
        if insight.variablesOverride:
            variables_override = {k: v.model_dump(mode="json") for k, v in insight.variablesOverride.items()}

        return InsightContext(
            team=self._team,
            query=insight.query,
            name=insight.name,
            description=insight.description,
            insight_id=insight.id,
            dashboard_filters=dashboard_filters,
            filters_override=filters_override,
            variables_override=variables_override,
        )

    async def _execute_and_format_insight(self, context: InsightContext) -> str | None:
        """
        Execute and format a single insight for AI consumption.

        Args:
            context: InsightContext to execute

        Returns:
            Formatted insight string or None if failed
        """
        try:
            insight_prompt = await context.execute_and_format()
            return format_prompt_string(
                ROOT_INSIGHT_CONTEXT_PROMPT,
                heading="##",
                insight_prompt=insight_prompt,
            )
        except Exception as err:
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

    async def _get_context_messages(self, state: BaseStateWithMessages) -> list[ContextMessage]:
        prompts: list[ContextMessage] = []
        if mode_prompt := self._get_mode_context_messages(state):
            prompts.append(mode_prompt)
        if contextual_tools := await self._get_contextual_tools_prompt():
            prompts.append(ContextMessage(content=contextual_tools, id=str(uuid4())))
        if ui_context := await self._format_ui_context(self.get_ui_context(state)):
            prompts.append(ContextMessage(content=ui_context, id=str(uuid4())))
        return self._deduplicate_context_messages(state, prompts)

    async def _get_contextual_tools_prompt(self) -> str | None:
        from ee.hogai.registry import get_contextual_tool_class

        contextual_tools_prompt: list[str] = []
        for tool_name, tool_context in self.get_contextual_tools().items():
            tool_class = get_contextual_tool_class(tool_name)
            if tool_class is None:
                continue
            tool = await tool_class.create_tool_class(team=self._team, user=self._user, context_manager=self)
            tool_prompt = tool.format_context_prompt_injection(tool_context)
            contextual_tools_prompt.append(f"<{tool_name}>\n" f"{tool_prompt}\n" f"</{tool_name}>")

        if contextual_tools_prompt:
            tools = "\n".join(contextual_tools_prompt)
            return CONTEXTUAL_TOOLS_REMINDER_PROMPT.format(tools=tools)
        return None

    def _deduplicate_context_messages(
        self, state: BaseStateWithMessages, context_messages: list[ContextMessage]
    ) -> list[ContextMessage]:
        """Naive deduplication of context messages by content."""
        existing_contents = {message.content for message in state.messages if isinstance(message, ContextMessage)}
        return [msg for msg in context_messages if msg.content not in existing_contents]

    def _inject_context_messages(
        self, state: BaseStateWithMessages, context_messages: list[ContextMessage]
    ) -> list[AssistantMessageUnion]:
        # Insert context messages right before the start message
        return insert_messages_before_start(state.messages, context_messages, start_id=state.start_id)

    def _get_mode_context_messages(self, state: BaseStateWithMessages) -> ContextMessage | None:
        """
        Returns a mode ContextMessage if one should be injected.
        - On first turn: inject initial mode prompt
        - On subsequent turns: inject switch prompt if mode changed
        """
        current_mode = state.agent_mode_or_default
        is_first_message = find_start_message_idx(state.messages, state.start_id) == 0

        if is_first_message:
            return self._create_mode_context_message(current_mode, is_initial=True)

        previous_mode = self._get_previous_mode_from_messages(state.messages)
        if previous_mode and previous_mode != current_mode:
            return self._create_mode_context_message(current_mode, is_initial=False)

        return None

    def _get_previous_mode_from_messages(self, messages: Sequence[AssistantMessageUnion]) -> AgentMode | None:
        """
        Extracts the most recent mode from existing messages.
        Checks ContextMessages metadata and AssistantMessages for switch_mode tool calls.
        """
        for message in reversed(messages):
            # Check for switch_mode tool calls
            if isinstance(message, AssistantMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.name == AssistantTool.SWITCH_MODE:
                        new_mode = tool_call.args.get("new_mode") if tool_call.args else None
                        if new_mode and new_mode in AgentMode.__members__.values():
                            return AgentMode(new_mode)
            # Check for mode context messages via metadata
            if isinstance(message, ContextMessage) and isinstance(message.meta, ModeContext):
                return message.meta.mode
        return None

    def _create_mode_context_message(self, mode: AgentMode, *, is_initial: bool) -> ContextMessage:
        mode_prompt = CONTEXT_INITIAL_MODE_PROMPT if is_initial else CONTEXT_MODE_SWITCH_PROMPT
        content = format_prompt_string(
            CONTEXT_MODE_PROMPT,
            mode_prompt=mode_prompt,
            mode=mode.value,
        )
        return ContextMessage(
            content=content,
            id=str(uuid4()),
            meta=ModeContext(mode=mode),
        )
