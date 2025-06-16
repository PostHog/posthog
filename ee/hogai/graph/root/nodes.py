import datetime
import importlib
import math
import pkgutil
from typing import Literal, Optional, TypeVar, cast
from uuid import uuid4

from django.conf import settings
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
    trim_messages,
)
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from posthoganalytics import capture_exception
from pydantic import BaseModel

import products
from ee.hogai.graph.memory.nodes import should_run_onboarding_before_insights
from ee.hogai.graph.query_executor.query_executor import AssistantQueryExecutor, SupportedQueryTypes
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL, create_and_query_insight, search_documentation
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql_queries.apply_dashboard_filters import (
    apply_dashboard_filters_to_dict,
    apply_dashboard_variables_to_dict,
)
from posthog.schema import (
    AssistantContextualTool,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    FailureMessage,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    MaxContextShape,
    MaxInsightContext,
    RetentionQuery,
    TrendsQuery,
)

from ..base import AssistantNode
from .prompts import (
    ROOT_DASHBOARD_CONTEXT_PROMPT,
    ROOT_DASHBOARDS_CONTEXT_PROMPT,
    ROOT_HARD_LIMIT_REACHED_PROMPT,
    ROOT_INSIGHT_CONTEXT_PROMPT,
    ROOT_INSIGHTS_CONTEXT_PROMPT,
    ROOT_SYSTEM_PROMPT,
    ROOT_USER_CONTEXT_PROMPT,
)

# TRICKY: Dynamically import max_tools from all products
for module_info in pkgutil.iter_modules(products.__path__):
    if module_info.name in ("conftest", "test"):
        continue  # We mustn't import test modules in prod
    try:
        importlib.import_module(f"products.{module_info.name}.backend.max_tools")
    except ModuleNotFoundError:
        pass  # Skip if backend or max_tools doesn't exist - note that the product's dir needs a top-level __init__.py


# Map query kinds to their respective full UI query classes
# NOTE: Update this and SupportedQueryTypes when adding new query types
MAX_SUPPORTED_QUERY_KIND_TO_MODEL: dict[str, type[SupportedQueryTypes]] = {
    "TrendsQuery": TrendsQuery,
    "FunnelsQuery": FunnelsQuery,
    "RetentionQuery": RetentionQuery,
    "HogQLQuery": HogQLQuery,
}


RouteName = Literal["insights", "root", "end", "search_documentation", "memory_onboarding"]


RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage
T = TypeVar("T", RootMessageUnion, BaseMessage)


class RootNodeUIContextMixin(AssistantNode):
    """Mixin that provides UI context formatting capabilities for root nodes."""

    def _format_ui_context(self, ui_context: Optional[MaxContextShape]) -> str:
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

        if dashboard_context or insights_context:
            return self._render_user_context_template(dashboard_context, insights_context)
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

    def _render_user_context_template(self, dashboard_context: str, insights_context: str) -> str:
        """Render the user context template with the provided context strings."""
        template = PromptTemplate.from_template(ROOT_USER_CONTEXT_PROMPT, template_format="mustache")
        return template.format_prompt(
            ui_context_dashboard=dashboard_context, ui_context_insights=insights_context
        ).to_string()


class RootNode(RootNodeUIContextMixin):
    MAX_TOOL_CALLS = 4
    """
    Determines the maximum number of tool calls allowed in a single generation.
    """
    CONVERSATION_WINDOW_SIZE = 64000
    """
    Determines the maximum number of tokens allowed in the conversation window.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        history, new_window_id = self._construct_and_update_messages_window(state, config)

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", ROOT_SYSTEM_PROMPT),
                    *[
                        (
                            "system",
                            f"<{tool_name}>\n"
                            f"{CONTEXTUAL_TOOL_NAME_TO_TOOL[AssistantContextualTool(tool_name)]().format_system_prompt_injection(tool_context)}\n"
                            f"</{tool_name}>",
                        )
                        for tool_name, tool_context in self._get_contextual_tools(config).items()
                        if tool_name in CONTEXTUAL_TOOL_NAME_TO_TOOL
                    ],
                ],
                template_format="mustache",
            )
            + history
        )
        chain = prompt | self._get_model(state, config)

        utc_now = datetime.datetime.now(datetime.UTC)
        project_now = utc_now.astimezone(self._team.timezone_info)

        ui_context = self._get_ui_context(state)
        user_context = self._format_ui_context(ui_context)

        message = chain.invoke(
            {
                "core_memory": self.core_memory_text,
                "utc_datetime_display": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_datetime_display": project_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_timezone": self._team.timezone_info.tzname(utc_now),
                "user_context": user_context,
            },
            config,
        )
        message = cast(LangchainAIMessage, message)

        return PartialAssistantState(
            root_conversation_start_id=new_window_id,
            messages=[
                AssistantMessage(
                    content=str(message.content),
                    tool_calls=[
                        AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"])
                        for tool_call in message.tool_calls
                    ],
                    id=str(uuid4()),
                ),
            ],
        )

    def _get_model(self, state: AssistantState, config: RunnableConfig):
        # Research suggests temperature is not _massively_ correlated with creativity (https://arxiv.org/html/2405.00492v1).
        # It _probably_ doesn't matter, but let's use a lower temperature for _maybe_ less of a risk of hallucinations.
        # We were previously using 0.0, but that wasn't useful, as the false determinism didn't help in any way,
        # only made evals less useful precisely because of the false determinism.
        base_model = ChatOpenAI(model="gpt-4o", temperature=0.3, streaming=True, stream_usage=True)

        # The agent can now be in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent doesn't have any other option but to exit.
        if self._is_hard_limit_reached(state):
            return base_model

        available_tools: list[type[BaseModel]] = []
        if settings.INKEEP_API_KEY:
            available_tools.append(search_documentation)
        tool_names = self._get_contextual_tools(config).keys()
        is_editing_insight = AssistantContextualTool.CREATE_AND_QUERY_INSIGHT in tool_names
        if not is_editing_insight:
            # This is the default tool, which can be overriden by the MaxTool based tool with the same name
            available_tools.append(create_and_query_insight)
        for tool_name in tool_names:
            try:
                ToolClass = CONTEXTUAL_TOOL_NAME_TO_TOOL[AssistantContextualTool(tool_name)]
            except ValueError:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            available_tools.append(ToolClass())  # type: ignore
        return base_model.bind_tools(available_tools, strict=True, parallel_tool_calls=False)

    def _get_assistant_messages_in_window(self, state: AssistantState) -> list[RootMessageUnion]:
        filtered_conversation = [message for message in state.messages if isinstance(message, RootMessageUnion)]
        if state.root_conversation_start_id is not None:
            filtered_conversation = self._get_conversation_window(
                filtered_conversation, state.root_conversation_start_id
            )
        return filtered_conversation

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        # Filter out messages that are not part of the conversation window.
        conversation_window = self._get_assistant_messages_in_window(state)

        # `assistant` messages must be contiguous with the respective `tool` messages.
        tool_result_messages = {
            message.tool_call_id: message
            for message in conversation_window
            if isinstance(message, AssistantToolCallMessage)
        }

        history: list[BaseMessage] = []
        for message in conversation_window:
            if isinstance(message, HumanMessage):
                history.append(LangchainHumanMessage(content=message.content, id=message.id))
            elif isinstance(message, AssistantMessage):
                # Filter out tool calls without a tool response, so the completion doesn't fail.
                tool_calls = [
                    tool for tool in (message.model_dump()["tool_calls"] or []) if tool["id"] in tool_result_messages
                ]

                history.append(LangchainAIMessage(content=message.content, tool_calls=tool_calls, id=message.id))

                # Append associated tool call messages.
                for tool_call in tool_calls:
                    tool_call_id = tool_call["id"]
                    result_message = tool_result_messages[tool_call_id]
                    history.append(
                        LangchainToolMessage(
                            content=result_message.content, tool_call_id=tool_call_id, id=result_message.id
                        )
                    )
            elif isinstance(message, FailureMessage):
                history.append(
                    LangchainAIMessage(content=message.content or "An unknown failure occurred.", id=message.id)
                )

        return history

    def _construct_and_update_messages_window(
        self, state: AssistantState, config: RunnableConfig
    ) -> tuple[list[BaseMessage], str | None]:
        """
        Retrieves the current conversation window, finds a new window if necessary, and enforces the tool call limit.
        """

        history = self._construct_messages(state)

        # Find a new window id and trim the history to it.
        new_window_id = self._find_new_window_id(state, config, history)
        if new_window_id is not None:
            history = self._get_conversation_window(history, new_window_id)

        # Force the agent to stop if the tool call limit is reached.
        if self._is_hard_limit_reached(state):
            history.append(LangchainHumanMessage(content=ROOT_HARD_LIMIT_REACHED_PROMPT))

        return history, new_window_id

    def _is_hard_limit_reached(self, state: AssistantState) -> bool:
        return state.root_tool_calls_count is not None and state.root_tool_calls_count >= self.MAX_TOOL_CALLS

    def _find_new_window_id(
        self, state: AssistantState, config: RunnableConfig, window: list[BaseMessage]
    ) -> str | None:
        """
        If we simply trim the conversation on N tokens, the cache will be invalidated for every new message after that
        limit leading to increased latency. Instead, when we hit the limit, we trim the conversation to N/2 tokens, so
        the cache invalidates only for the next generation.
        """
        model = self._get_model(state, config)

        if model.get_num_tokens_from_messages(window) > self.CONVERSATION_WINDOW_SIZE:
            trimmed_window: list[BaseMessage] = trim_messages(
                window,
                token_counter=model,
                max_tokens=math.floor(self.CONVERSATION_WINDOW_SIZE / 2),
                start_on="human",
                end_on=("human", "tool"),
                allow_partial=False,
            )
            if len(trimmed_window) != len(window):
                if trimmed_window:
                    new_start_id = trimmed_window[0].id
                    return new_start_id
                # We don't want the conversation to be completely empty.
                if isinstance(window[-1], LangchainHumanMessage):
                    return window[-1].id
                if len(window) > 1 and isinstance(window[-2], LangchainAIMessage):
                    return window[-2].id
        return None

    def _get_conversation_window(self, messages: list[T], start_id: str) -> list[T]:
        for idx, message in enumerate(messages):
            if message.id == start_id:
                return messages[idx:]
        return messages


class RootNodeTools(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            # Reset tools.
            return PartialAssistantState(root_tool_calls_count=0)

        tool_call_count = state.root_tool_calls_count or 0

        tools_calls = last_message.tool_calls
        if len(tools_calls) != 1:
            raise ValueError("Expected exactly one tool call.")

        tool_names = self._get_contextual_tools(config).keys()
        is_editing_insight = AssistantContextualTool.CREATE_AND_QUERY_INSIGHT in tool_names
        tool_call = tools_calls[0]
        if tool_call.name == "create_and_query_insight" and not is_editing_insight:
            return PartialAssistantState(
                root_tool_call_id=tool_call.id,
                root_tool_insight_plan=tool_call.args["query_description"],
                root_tool_insight_type=tool_call.args["query_kind"],
                root_tool_calls_count=tool_call_count + 1,
            )
        elif tool_call.name == "search_documentation":
            return PartialAssistantState(
                root_tool_call_id=tool_call.id,
                root_tool_insight_plan=None,  # No insight plan here
                root_tool_insight_type=None,  # No insight type here
                root_tool_calls_count=tool_call_count + 1,
            )
        elif ToolClass := CONTEXTUAL_TOOL_NAME_TO_TOOL.get(cast(AssistantContextualTool, tool_call.name)):
            tool_class = ToolClass(state)
            result = tool_class.invoke(tool_call.model_dump(), config)
            assert isinstance(result, LangchainToolMessage)

            new_state = tool_class._state  # latest state, in case the tool has updated it
            last_message = new_state.messages[-1]
            if isinstance(last_message, AssistantToolCallMessage) and last_message.tool_call_id == tool_call.id:
                return PartialAssistantState(
                    messages=new_state.messages[
                        len(state.messages) :
                    ],  # we send all messages from the tool call onwards
                    root_tool_call_id=None,  # Tool handled already
                    root_tool_insight_plan=None,  # No insight plan here
                    root_tool_insight_type=None,  # No insight type here
                    root_tool_calls_count=tool_call_count + 1,
                )

            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=str(result.content) if result.content else "",
                        ui_payload={tool_call.name: result.artifact},
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                        visible=True,
                    )
                ],
                root_tool_call_id=None,  # Tool handled already
                root_tool_insight_plan=None,  # No insight plan here
                root_tool_insight_type=None,  # No insight type here
                root_tool_calls_count=tool_call_count + 1,
            )
        else:
            raise ValueError(f"Unknown tool called: {tool_call.name}")

    def router(self, state: AssistantState) -> RouteName:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantToolCallMessage):
            return "root"  # Let the root either proceed or finish, since it now can see the tool call result
        if state.root_tool_call_id:
            if state.root_tool_insight_type:
                if should_run_onboarding_before_insights(self._team, state) == "memory_onboarding":
                    return "memory_onboarding"
                return "insights"
            else:
                return "search_documentation"
        return "end"
