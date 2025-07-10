from typing import Literal, TypeVar, cast
from uuid import uuid4

from django.conf import settings
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.errors import NodeInterrupt
from pydantic import BaseModel

from ee.hogai.graph.memory.nodes import should_run_onboarding_before_insights
from ee.hogai.graph.root.mixin.conversation_history import ConversationHistoryNodeMixin
from ee.hogai.graph.root.mixin.ui_context import UIContextNodeMixin
from ee.hogai.graph.shared_prompts import PROJECT_ORG_USER_CONTEXT_PROMPT

# Import moved inside functions to avoid circular imports
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantContextualTool,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
)

from ..base import AssistantNode
from .prompts import (
    ROOT_SYSTEM_PROMPT,
)


RouteName = Literal["insights", "root", "end", "search_documentation", "memory_onboarding"]


RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage
T = TypeVar("T", RootMessageUnion, BaseMessage)


class RootNode(UIContextNodeMixin, ConversationHistoryNodeMixin):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        from ee.hogai.tool import get_contextual_tool_class

        history, new_window_id = self._construct_and_update_messages_window(state, config)

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", ROOT_SYSTEM_PROMPT),
                    ("system", PROJECT_ORG_USER_CONTEXT_PROMPT),
                    *[
                        (
                            "system",
                            f"<{tool_name}>\n"
                            f"{get_contextual_tool_class(tool_name)().format_system_prompt_injection(tool_context)}\n"  # type: ignore
                            f"</{tool_name}>",
                        )
                        for tool_name, tool_context in self._get_contextual_tools(config).items()
                        if get_contextual_tool_class(tool_name) is not None
                    ],
                ],
                template_format="mustache",
            )
            + history
        )
        chain = prompt | self._get_model(state, config)

        ui_context = self._format_ui_context(self._get_ui_context(state))

        message = chain.invoke(
            {
                "core_memory": self.core_memory_text,
                "project_datetime": self.project_now,
                "project_timezone": self.project_timezone,
                "project_name": self._team.name,
                "organization_name": self._team.organization.name,
                "user_full_name": self._user.get_full_name(),
                "user_email": self._user.email,
                "ui_context": ui_context,
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
        base_model = ChatOpenAI(model="gpt-4o", temperature=0.3, streaming=True, stream_usage=True, max_retries=3)

        # The agent can now be in loops. Since insight building is an expensive operation, we want to limit a recursion depth.
        # This will remove the functions, so the agent doesn't have any other option but to exit.
        if self._is_hard_limit_reached(state):
            return base_model

        from ee.hogai.tool import create_and_query_insight, get_contextual_tool_class, search_documentation

        available_tools: list[type[BaseModel]] = []
        if settings.INKEEP_API_KEY:
            available_tools.append(search_documentation)
        tool_names = self._get_contextual_tools(config).keys()
        is_editing_insight = AssistantContextualTool.CREATE_AND_QUERY_INSIGHT in tool_names
        if not is_editing_insight:
            # This is the default tool, which can be overriden by the MaxTool based tool with the same name
            available_tools.append(create_and_query_insight)
        for tool_name in tool_names:
            ToolClass = get_contextual_tool_class(tool_name)
            if ToolClass is None:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            available_tools.append(ToolClass())  # type: ignore
        return base_model.bind_tools(available_tools, strict=True, parallel_tool_calls=False)


class RootNodeTools(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
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

        from ee.hogai.tool import get_contextual_tool_class

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
        elif ToolClass := get_contextual_tool_class(tool_call.name):
            tool_class = ToolClass(state)
            result = await tool_class.ainvoke(tool_call.model_dump(), config)
            if not isinstance(result, LangchainToolMessage):
                raise TypeError(f"Expected a {LangchainToolMessage}, got {type(result)}")

            # If this is a navigation tool call, pause the graph execution
            # so that the frontend can re-initialise Max with a new set of contextual tools.
            if tool_call.name == "navigate":
                navigate_message = AssistantToolCallMessage(
                    content=str(result.content) if result.content else "",
                    ui_payload={tool_call.name: result.artifact},
                    id=str(uuid4()),
                    tool_call_id=tool_call.id,
                    visible=True,
                )
                # Raising a `NodeInterrupt` ensures the assistant graph stops here and
                # surfaces the navigation confirmation to the client. The next user
                # interaction will resume the graph with potentially different
                # contextual tools.
                raise NodeInterrupt(navigate_message)

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
