from unittest.mock import patch

from langchain_core.runnables import RunnableConfig

from ee.hogai.session_recordings_filters.nodes import SessionRecordingsFiltersNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantToolCallMessage, HumanMessage
from posthog.session_recordings.ai_data.ai_filter_schema import (
    AiFilterSchema,
    FilterData,
    OuterFilterGroup,
    FilterGroup,
    FilterValue,
    ResultEnum,
    FilterTypeEnum,
    FilterOperatorEnum,
    LogicGroupTypeEnum,
)
from posthog.test.base import BaseTest


class TestSessionRecordingsFiltersNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.node = SessionRecordingsFiltersNode(self.team)

    @patch("ee.hogai.session_recordings_filters.nodes.ChatOpenAI")
    def test_run_returns_tool_call_message(self, mock_chat_openai):
        # Arrange
        mock_model = mock_chat_openai.return_value.with_structured_output.return_value
        mock_chain = mock_model.return_value

        # Mock the AI response
        mock_result = AiFilterSchema(
            result=ResultEnum.FILTER,
            data=FilterData(
                question="Show me recordings with errors",
                date_from="-5d",
                date_to="",
                filter_group=OuterFilterGroup(
                    type=LogicGroupTypeEnum.AND,
                    values=[
                        FilterGroup(
                            type=LogicGroupTypeEnum.AND,
                            values=[
                                FilterValue(
                                    key="level",
                                    type=FilterTypeEnum.LOG_ENTRY,
                                    value=["error"],
                                    operator=FilterOperatorEnum.EXACT,
                                )
                            ],
                        )
                    ],
                ),
            ),
        )

        mock_chain.invoke.return_value = mock_result

        # Create a state with a human message
        state = AssistantState(messages=[HumanMessage(content="Show me recordings with errors")])

        # Act
        result = self.node.run(state, RunnableConfig())

        # Assert
        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        assert result.messages[0].tool == "session_recordings_filters"
        assert result.messages[0].tool_input == "Show me recordings with errors"
        assert result.messages[0].ui_payload == mock_result.model_dump()
