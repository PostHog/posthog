from posthog.test.base import BaseTest
from unittest.mock import patch

from langgraph.errors import GraphInterrupt
from parameterized import parameterized

from posthog.schema import MultiQuestionForm, MultiQuestionFormQuestion

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
                title=f"Question {i}?",
                question=f"Question {i}?",
                options=[{"value": "Option A"}, {"value": "Option B"}],
            )
            for i in range(count)
        ]

    async def test_calls_interrupt_with_form(self):
        tool = self._create_tool()
        questions = self._create_questions(2)

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.side_effect = GraphInterrupt()

            with self.assertRaises(GraphInterrupt):
                await tool._arun_impl(questions=questions)

            # Verify interrupt was called with the correct form structure
            mock_interrupt.assert_called_once()
            call_args = mock_interrupt.call_args
            form = call_args.kwargs["value"]
            self.assertIsInstance(form, MultiQuestionForm)
            self.assertEqual(len(form.questions), 2)

    async def test_raises_retryable_error_when_more_than_4_questions(self):
        tool = self._create_tool()
        questions = self._create_questions(5)

        with self.assertRaises(MaxToolRetryableError) as context:
            await tool._arun_impl(questions=questions)

        self.assertIn("Do not ask more than 4 questions", str(context.exception))

    async def test_raises_retryable_error_when_empty_questions(self):
        tool = self._create_tool()

        with self.assertRaises(MaxToolRetryableError) as context:
            await tool._arun_impl(questions=[])

        self.assertIn("At least one question is required", str(context.exception))

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

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.side_effect = GraphInterrupt()

            with self.assertRaises(GraphInterrupt):
                await tool._arun_impl(questions=questions)

            # Verify interrupt was called (validation passed)
            mock_interrupt.assert_called_once()
