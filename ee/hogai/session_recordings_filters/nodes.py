from typing import Optional, cast
from uuid import uuid4

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.session_recordings_filters.prompts import SESSION_RECORDINGS_FILTERS_PROMPT
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantContextualTool, AssistantToolCallMessage, HumanMessage
from posthog.session_recordings.ai_data.ai_filter_schema import AiFilterSchema


class SessionRecordingsFiltersNode(AssistantNode):
    """
    Node for generating session recording filters using AI.

    This node takes a user query about session recordings and generates
    structured filters that can be applied to the list of recordings.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        latest_human_message: Optional[HumanMessage] = next(
            (msg for msg in reversed(state.messages) if isinstance(msg, HumanMessage)), None
        )

        if latest_human_message is None:
            raise ValueError("No human message found in the state")

        model = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
        ).with_structured_output(
            AiFilterSchema,
            include_raw=False,
        )

        prompt = ChatPromptTemplate(
            [
                ("system", SESSION_RECORDINGS_FILTERS_PROMPT),
                ("human", "{{{query}}}"),
            ],
            template_format="mustache",
        )

        chain = prompt | model

        result = cast(AiFilterSchema, chain.invoke({"query": latest_human_message.content}, config))

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    id=str(uuid4()),
                    content="✅ Updated session recordings filters.",
                    tool_call_id=state.root_tool_call_id,
                    ui_payload={AssistantContextualTool.SEARCH_SESSION_RECORDINGS: result.model_dump()},
                )
            ],
            # Resetting values to empty strings because Nones are not supported by LangGraph.
            root_tool_call_id="",
            root_tool_insight_plan="",
            root_tool_insight_type="",
        )
