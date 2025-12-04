from posthog.test.base import BaseTest

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage, MaxUIContext

from ee.hogai.core.runner import BaseAgentRunner
from ee.hogai.utils.types import AssistantState


class MockAgentRunner(BaseAgentRunner):
    """Minimal concrete implementation for testing BaseAgentRunner methods."""

    def __init__(self, team, user, latest_message=None):
        self._team = team
        self._user = user
        self._latest_message = latest_message

    def get_initial_state(self) -> AssistantState:
        return AssistantState(messages=[])

    def get_resumed_state(self):
        return {}


class TestGetFormResponseMessage(BaseTest):
    def setUp(self):
        super().setUp()

    def _create_runner_with_message(self, latest_message):
        return MockAgentRunner(team=self.team, user=self.user, latest_message=latest_message)

    def test_returns_none_when_no_messages(self):
        runner = self._create_runner_with_message(HumanMessage(content="Test"))
        saved_state = AssistantState(messages=[])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNone(result)

    def test_returns_none_when_no_latest_message(self):
        runner = self._create_runner_with_message(None)
        saved_state = AssistantState(messages=[AssistantToolCallMessage(content="test", tool_call_id="tc1")])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNone(result)

    def test_returns_none_when_latest_message_is_not_human_message(self):
        runner = self._create_runner_with_message(
            AssistantToolCallMessage(content="Tool response", tool_call_id="some-id")
        )
        assistant_message = AssistantMessage(
            content="Please answer:",
            tool_calls=[
                AssistantToolCall(
                    id="create_form_tc_1",
                    name="create_form",
                    args={"questions": [{"id": "q1", "question": "Question 1"}]},
                    type="tool_call",
                )
            ],
        )
        saved_state = AssistantState(messages=[assistant_message])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNone(result)

    def test_returns_none_when_no_form_answers_in_ui_context(self):
        runner = self._create_runner_with_message(HumanMessage(content="My answer"))
        assistant_message = AssistantMessage(
            content="test",
            tool_calls=[AssistantToolCall(id="tc1", name="create_form", args={}, type="tool_call")],
        )
        saved_state = AssistantState(messages=[assistant_message])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNone(result)

    def test_returns_none_when_no_create_form_tool_call(self):
        runner = self._create_runner_with_message(
            HumanMessage(content="My answer", ui_context=MaxUIContext(form_answers={"q1": "answer"}))
        )
        assistant_message = AssistantMessage(
            content="test",
            tool_calls=[AssistantToolCall(id="tc1", name="other_tool", args={}, type="tool_call")],
        )
        saved_state = AssistantState(messages=[assistant_message])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNone(result)

    def test_creates_tool_call_message_with_form_answers(self):
        user_content = "What is your name: John\nWhat is your role: Engineer"
        message = HumanMessage(
            content=user_content, ui_context=MaxUIContext(form_answers={"name": "John", "role": "Engineer"})
        )
        runner = self._create_runner_with_message(message)

        tool_call_id = "create_form_tc_1"
        assistant_message = AssistantMessage(
            content="Please answer these questions:",
            tool_calls=[
                AssistantToolCall(
                    id=tool_call_id,
                    name="create_form",
                    args={
                        "questions": [
                            {"id": "name", "question": "What is your name"},
                            {"id": "role", "question": "What is your role"},
                        ]
                    },
                    type="tool_call",
                )
            ],
        )
        saved_state = AssistantState(messages=[assistant_message])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, AssistantToolCallMessage)
        assert isinstance(result, AssistantToolCallMessage)
        self.assertEqual(result.content, user_content)
        self.assertEqual(result.tool_call_id, tool_call_id)
        self.assertIsNotNone(result.ui_payload)
        assert result.ui_payload is not None
        self.assertIn("create_form", result.ui_payload)
        self.assertEqual(
            result.ui_payload["create_form"]["answers"],
            {"name": "John", "role": "Engineer"},
        )

    def test_builds_correct_ui_payload_structure(self):
        user_content = "Pick a color: Blue"
        message = HumanMessage(content=user_content, ui_context=MaxUIContext(form_answers={"color": "Blue"}))
        runner = self._create_runner_with_message(message)

        tool_call_id = "form_tc_123"
        assistant_message = AssistantMessage(
            content="Choose your favorite color:",
            tool_calls=[
                AssistantToolCall(
                    id=tool_call_id,
                    name="create_form",
                    args={
                        "questions": [
                            {"id": "color", "question": "Pick a color"},
                        ]
                    },
                    type="tool_call",
                )
            ],
        )
        saved_state = AssistantState(messages=[assistant_message])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNotNone(result)
        assert isinstance(result, AssistantToolCallMessage)
        assert result.ui_payload is not None
        self.assertEqual(result.ui_payload, {"create_form": {"answers": {"color": "Blue"}}})

    def test_returns_none_with_empty_form_answers_dict(self):
        user_content = "What is your name: John"
        ui_context = MaxUIContext(form_answers={})  # Empty dict
        runner = self._create_runner_with_message(HumanMessage(content=user_content, ui_context=ui_context))

        tool_call_id = "create_form_tc_1"
        assistant_message = AssistantMessage(
            content="Please answer:",
            tool_calls=[
                AssistantToolCall(
                    id=tool_call_id,
                    name="create_form",
                    args={"questions": [{"id": "name", "question": "What is your name"}]},
                    type="tool_call",
                )
            ],
        )
        saved_state = AssistantState(messages=[assistant_message])

        result = runner._get_form_response_message(saved_state)

        self.assertIsNone(result)
