from posthog.test.base import BaseTest
from unittest.mock import patch

from langgraph.errors import GraphInterrupt
from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import MultiQuestionForm, MultiQuestionFormField, MultiQuestionFormQuestion

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

    @parameterized.expand(
        [
            ("select",),
            ("multi_select",),
        ]
    )
    async def test_raises_retryable_error_when_options_missing_for_selection_type(self, field_type: str):
        tool = self._create_tool()
        questions = [
            MultiQuestionFormQuestion(
                id="q1",
                title="Test",
                question="Test?",
                type=field_type,
            )
        ]

        with self.assertRaises(MaxToolRetryableError) as context:
            await tool._arun_impl(questions=questions)

        self.assertIn("requires options", str(context.exception))

    @parameterized.expand(
        [
            ("text",),
            ("number",),
            ("slider",),
            ("toggle",),
            ("dropdown",),
        ]
    )
    def test_schema_rejects_non_selection_types_on_question(self, field_type: str):
        with self.assertRaises(ValidationError):
            MultiQuestionFormQuestion(
                id="q1",
                title="Test",
                question="Test?",
                type=field_type,
            )

    @parameterized.expand(
        [
            ("string answer", {"q0": "Option A"}, "Question 0?: Option A"),
            ("list answer", {"q0": ["Option A", "Option B"]}, "Question 0?: Option A, Option B"),
            ("missing answer", {}, "Question 0?: (skipped)"),
        ]
    )
    async def test_formats_answers(self, _name: str, answers: dict, expected_line: str):
        tool = self._create_tool()
        questions = self._create_questions(1)

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"action": "form", "form_answers": answers}

            result, metadata = await tool._arun_impl(questions=questions)

            self.assertEqual(result, expected_line)
            self.assertEqual(metadata["answers"], answers)

    def _create_multi_field_question(self, fields: list[MultiQuestionFormField]) -> MultiQuestionFormQuestion:
        return MultiQuestionFormQuestion(
            id="config",
            title="Config",
            type="multi_field",
            question="Configure settings",
            fields=fields,
        )

    @parameterized.expand(
        [
            ("select",),
            ("multi_select",),
        ]
    )
    def test_schema_rejects_selection_types_in_fields(self, field_type: str):
        with self.assertRaises(ValidationError):
            MultiQuestionFormField(id="f1", type=field_type, label="Test field")

    async def test_multi_field_with_no_fields_passes_through(self):
        tool = self._create_tool()
        question = MultiQuestionFormQuestion(
            id="config",
            title="Config",
            type="multi_field",
            question="Configure settings",
        )

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.side_effect = GraphInterrupt()

            with self.assertRaises(GraphInterrupt):
                await tool._arun_impl(questions=[question])

            mock_interrupt.assert_called_once()

    async def test_multi_field_raises_error_when_dropdown_missing_options(self):
        tool = self._create_tool()
        question = self._create_multi_field_question(
            [
                MultiQuestionFormField(id="f1", type="dropdown", label="Test dropdown"),
            ]
        )

        with self.assertRaises(MaxToolRetryableError) as context:
            await tool._arun_impl(questions=[question])

        self.assertIn("requires options", str(context.exception))
        self.assertIn("f1", str(context.exception))

    async def test_multi_field_raises_error_when_slider_missing_min_max(self):
        tool = self._create_tool()
        question = self._create_multi_field_question(
            [
                MultiQuestionFormField(id="f1", type="slider", label="Slider field"),
            ]
        )

        with self.assertRaises(MaxToolRetryableError) as context:
            await tool._arun_impl(questions=[question])

        self.assertIn("requires min and max", str(context.exception))
        self.assertIn("f1", str(context.exception))

    async def test_multi_field_merges_multiple_composites(self):
        tool = self._create_tool()
        q1 = self._create_multi_field_question(
            [
                MultiQuestionFormField(id="f1", type="toggle", label="Toggle 1"),
            ]
        )
        q2 = MultiQuestionFormQuestion(
            id="config2",
            title="Config2",
            type="multi_field",
            question="More settings",
            fields=[MultiQuestionFormField(id="f2", type="toggle", label="Toggle 2")],
        )

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.side_effect = GraphInterrupt()

            with self.assertRaises(GraphInterrupt):
                await tool._arun_impl(questions=[q1, q2])

            form = mock_interrupt.call_args.kwargs["value"]
            # Should have merged into one multi_field question with both fields
            multi_field_qs = [q for q in form.questions if (q.type or "select") == "multi_field"]
            self.assertEqual(len(multi_field_qs), 1)
            self.assertEqual(len(multi_field_qs[0].fields), 2)
            field_ids = [f.id for f in multi_field_qs[0].fields]
            self.assertIn("f1", field_ids)
            self.assertIn("f2", field_ids)

    async def test_multi_field_valid_question_passes_validation(self):
        tool = self._create_tool()
        question = self._create_multi_field_question(
            [
                MultiQuestionFormField(id="sample", type="number", label="Sample size", min=100, max=10000),
                MultiQuestionFormField(id="confidence", type="slider", label="Confidence", min=80, max=99),
                MultiQuestionFormField(id="notify", type="toggle", label="Notify me"),
            ]
        )

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.side_effect = GraphInterrupt()

            with self.assertRaises(GraphInterrupt):
                await tool._arun_impl(questions=[question])

            mock_interrupt.assert_called_once()

    async def test_multi_field_formats_answers_with_indentation(self):
        tool = self._create_tool()
        question = self._create_multi_field_question(
            [
                MultiQuestionFormField(id="sample", type="number", label="Sample size"),
                MultiQuestionFormField(id="notify", type="toggle", label="Notify me"),
            ]
        )

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "form",
                "form_answers": {"sample": "1000", "notify": "true"},
            }

            result, metadata = await tool._arun_impl(questions=[question])

            self.assertEqual(
                result,
                "Configure settings:\n  Sample size: 1000\n  Notify me: true",
            )
            self.assertEqual(metadata["answers"], {"sample": "1000", "notify": "true"})

    async def test_formats_skipped_questions(self):
        tool = self._create_tool()
        questions = self._create_questions(2)

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "form",
                "form_answers": {"q0": "Option A"},
            }

            result, metadata = await tool._arun_impl(questions=questions)

            self.assertEqual(
                result,
                "Question 0?: Option A\nQuestion 1?: (skipped)",
            )
            self.assertEqual(metadata["answers"], {"q0": "Option A"})

    async def test_returns_dismissed_response_when_user_dismisses_form(self):
        tool = self._create_tool()
        questions = self._create_questions(1)

        with patch("ee.hogai.tools.create_form.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"action": "dismiss_form"}

            result, metadata = await tool._arun_impl(questions=questions)

            self.assertIn("dismissed the form", result)
            self.assertEqual(metadata, {"status": "dismiss_form"})
