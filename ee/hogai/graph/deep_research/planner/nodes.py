from ee.hogai.graph.deep_research.base import DeepResearchNode
from ee.hogai.graph.root.mixin.conversation_history import ConversationHistoryNodeMixin
from ee.hogai.utils.types import DeepResearchPlan, DeepResearchPlanWithResults
from ee.hogai.graph.deep_research.planner.prompts import (
    DEEP_RESEARCH_PLANNER_CREATE_AND_QUERY_INSIGHT_PROMPT,
    DEEP_RESEARCH_PLANNER_PROMPT_FIRST_EXECUTION,
    DEEP_RESEARCH_PLANNER_REPLAN_PROMPT,
)
from langchain_openai import ChatOpenAI
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import ChatPromptTemplate
from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
)
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
)


class new_plan(BaseModel):
    """
    Plan the best way to answer the user's question, instructing agents to do the work.
    """

    plan: DeepResearchPlan = Field(description="A step-by-step list of TO-DOs for answering the user's question")


class confirm_plan(BaseModel):
    """
    Confirm the existing plan. The next TO-DO in the plan will be executed by the next agent.
    """


class complete_research(BaseModel):
    """
    Complete the research and return the final results to the user.
    """

    final_comment: str = Field(description="A comment to the user about the final results of the research")


class ask_user(BaseModel):
    """
    Ask the user for more information to help you plan the best way to answer the user's question.
    """

    question: str = Field(description="The question you are asking the user for more information about")


class DeepResearchPlannerNode(DeepResearchNode, ConversationHistoryNodeMixin):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        history = self._construct_messages(state)
        _prompt = (
            DEEP_RESEARCH_PLANNER_PROMPT_FIRST_EXECUTION
            if not state.deep_research_plan
            else DEEP_RESEARCH_PLANNER_REPLAN_PROMPT
        )
        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", _prompt),
                ],
                template_format="mustache",
            )
            + history
        )

        chain = prompt | self._get_model(state, config)

        invoke_kwargs = {
            "core_memory": await self._aget_core_memory(),
            "create_and_query_insight_guidelines": DEEP_RESEARCH_PLANNER_CREATE_AND_QUERY_INSIGHT_PROMPT,
        }
        if state.deep_research_plan:
            invoke_kwargs["existing_plan"] = self._format_plan_xml(state.deep_research_plan)

        message = await chain.ainvoke(
            invoke_kwargs,
            config,
        )
        message = cast(LangchainAIMessage, message)

        return PartialAssistantState(
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
        base_model = ChatOpenAI(model="o3", streaming=True, stream_usage=True, max_retries=3)

        available_tools: list[type[BaseModel]] = [new_plan]

        if state.deep_research_plan:
            available_tools += [confirm_plan, complete_research]
        else:
            available_tools.append(ask_user)

        return base_model.bind_tools(available_tools, strict=True)


class DeepResearchPlannerToolsNode(DeepResearchNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            raise ValueError("Last message is not an assistant message.")

        if not last_message.tool_calls:
            return PartialAssistantState(
                messages=[last_message],
            )

        tools_calls = last_message.tool_calls
        if len(tools_calls) != 1:
            raise ValueError("Expected exactly one tool call.")

        tool_call = tools_calls[0]
        if tool_call.name == "new_plan":
            plan = tool_call.args["plan"]
            scratchpad = plan["scratchpad"]
            results = state.deep_research_plan.results if state.deep_research_plan else {}
            deep_research_plan = DeepResearchPlanWithResults.model_validate(
                {"scratchpad": scratchpad, "todos": plan["todos"], "results": results}
            )
            await self._save_deep_research_plan(deep_research_plan, config)

            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="new_plan",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                    AssistantMessage(
                        content=scratchpad,
                        id=str(uuid4()),
                    ),
                    AssistantMessage(
                        content=self._format_plan_string(deep_research_plan),
                        id=str(uuid4()),
                    ),
                ],
                deep_research_plan=deep_research_plan,
            )
        elif tool_call.name == "ask_user":
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="ask_user",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                    AssistantMessage(
                        content=tool_call.args["question"],
                        id=str(uuid4()),
                    ),
                ]
            )
        elif tool_call.name == "confirm_plan":
            return PartialAssistantState(
                messages=[AssistantToolCallMessage(content="confirm_plan", id=str(uuid4()), tool_call_id=tool_call.id)],
                deep_research_plan=state.deep_research_plan,
            )
        elif tool_call.name == "complete_research":
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(content="complete_research", id=str(uuid4()), tool_call_id=tool_call.id),
                    AssistantMessage(
                        content=tool_call.args["final_comment"],
                        id=str(uuid4()),
                    ),
                ],
            )
        else:
            raise ValueError(f"Unknown tool called: {tool_call.name}")

    def router(self, state: AssistantState) -> Literal["continue", "complete_research", "end"]:
        last_tool_call_message = find_last_message_of_type(state.messages, AssistantToolCallMessage)
        if last_tool_call_message:
            if last_tool_call_message.content == "new_plan":
                return "continue"
            elif last_tool_call_message.content == "complete_research":
                return "complete_research"
            elif last_tool_call_message.content == "confirm_plan":
                return "continue"
            elif last_tool_call_message.content == "ask_user":
                return "end"
            else:
                raise ValueError(f"Unknown tool call message: {last_tool_call_message.content}")
        return "end"
