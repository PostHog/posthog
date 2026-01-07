import pytest
from posthog.test.base import BaseTest

from langgraph.errors import NodeInterrupt
from parameterized import parameterized

from posthog.schema import MultiQuestionFormQuestion

from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.create_form import CreateFormTool
from ee.hogai.utils.types.base import NodePath


class TestCreateFormTool(BaseTest):
    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"

    def _create_tool(self) -> CreateFormTool:
        return CreateFormTool(
            team=self.team,
            user=self.user,
            tool_call_id=self.tool_call_id,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    def _create_questions(self, count: int) -> list[MultiQuestionFormQuestion]:
        return [
            MultiQuestionFormQuestion(
                id=f"q{i}",
                question=f"Question {i}?",
                options=[{"value": "Option A"}, {"value": "Option B"}],
            )
            for i in range(count)
        ]

    async def test_raises_node_interrupt_with_none(self):
        tool = self._create_tool()
        questions = self._create_questions(2)

        with pytest.raises(NodeInterrupt) as context:
            await tool._arun_impl(questions=questions)

        # NodeInterrupt wraps the value in an Interrupt object inside a list
        interrupt_list = context.value.args[0]
        assert len(interrupt_list) == 1
        interrupt_value = interrupt_list[0].value
        assert interrupt_value is None

    async def test_raises_retryable_error_when_more_than_4_questions(self):
        tool = self._create_tool()
        questions = self._create_questions(5)

        with pytest.raises(MaxToolRetryableError) as context:
            await tool._arun_impl(questions=questions)

        assert "Do not ask more than 4 questions" in str(context.value)

    async def test_raises_retryable_error_when_empty_questions(self):
        tool = self._create_tool()

        with pytest.raises(MaxToolRetryableError) as context:
            await tool._arun_impl(questions=[])

        assert "At least one question is required" in str(context.value)

    @parameterized.expand(
        [
            (1,),
            (2,),
            (3,),
            (4,),
        ]
    )
    async def test_accepts_valid_question_counts(self, question_count: int):
        tool = self._create_tool()
        questions = self._create_questions(question_count)

        with pytest.raises(NodeInterrupt):
            await tool._arun_impl(questions=questions)
