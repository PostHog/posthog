from uuid import uuid4

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.session_recordings_filters.prompts import (
    AI_FILTER_INITIAL_PROMPT,
    AI_FILTER_PROPERTIES_PROMPT,
    AI_FILTER_REQUEST_PROMPT,
)
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantContextualTool, AssistantToolCallMessage, MaxRecordingUniversalFilters


class SessionRecordingsFiltersNode(AssistantNode):
    """
    Node for generating session recording filters using AI.

    This node takes a user query about session recordings and generates
    structured filters that can be applied to the list of recordings.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        assert state.root_tool_call_id is not None
        tool_call = self._get_tool_call(state.messages, state.root_tool_call_id)

        model = (
            ChatOpenAI(model="gpt-4o", temperature=0.2)
            .with_structured_output(MaxRecordingUniversalFilters, include_raw=False)
            .with_retry()
        )

        prompt = ChatPromptTemplate(
            [
                ("system", AI_FILTER_INITIAL_PROMPT + AI_FILTER_PROPERTIES_PROMPT),
                ("human", AI_FILTER_REQUEST_PROMPT),
            ],
            template_format="mustache",
        )

        chain = prompt | model

        search_recordings_config = self._get_contextual_tools(config).get(
            AssistantContextualTool.SEARCH_SESSION_RECORDINGS, {}
        )
        result = chain.invoke(
            {
                "change": tool_call.args["change"],
                **search_recordings_config,
            },
            config,
        )
        assert isinstance(result, MaxRecordingUniversalFilters)

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
