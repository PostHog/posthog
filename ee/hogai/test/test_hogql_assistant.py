import json
from typing import Any, Optional, cast
from unittest.mock import patch

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from ee.hogai.utils.types import PartialAssistantState
from ee.models.assistant import Conversation, CoreMemory
from posthog.schema import (
    AssistantMessage,
    HumanMessage,
)
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event, _create_person

from ..hogql_assistant import HogQLAssistant
from ..hogql_graph import HogQLGraph


class TestHogQLAssistant(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.core_memory = CoreMemory.objects.create(
            team=self.team,
            text="Initial memory.",
            initial_text="Initial memory.",
            scraping_status=CoreMemory.ScrapingStatus.COMPLETED,
        )

    def _set_up_onboarding_tests(self):
        self.core_memory.delete()
        _create_person(
            distinct_ids=["person1"],
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$host": "us.posthog.com"},
        )

    def _parse_stringified_message(self, message: str) -> tuple[str, Any]:
        event_line, data_line, *_ = cast(str, message).split("\n")
        return (event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))

    def _run_assistant_graph(
        self,
        test_graph: Optional[CompiledStateGraph] = None,
        message: Optional[str] = "Hello",
        conversation: Optional[Conversation] = None,
        is_new_conversation: bool = False,
    ) -> list[tuple[str, Any]]:
        # Create assistant instance with our test graph
        assistant = HogQLAssistant(
            self.team,
            conversation or self.conversation,
            HumanMessage(content=message),
            self.user,
            is_new_conversation=is_new_conversation,
        )
        if test_graph:
            assistant._graph = test_graph
        # Capture and parse output of assistant.stream()
        output: list[tuple[str, Any]] = []
        for message in assistant.stream():
            output.append(self._parse_stringified_message(message))
        return output

    def assertConversationEqual(self, output: list[tuple[str, Any]], expected_output: list[tuple[str, Any]]):
        self.assertEqual(len(output), len(expected_output), output)
        for i, ((output_msg_type, output_msg), (expected_msg_type, expected_msg)) in enumerate(
            zip(output, expected_output)
        ):
            self.assertEqual(output_msg_type, expected_msg_type, f"Message type mismatch at index {i}")
            msg_dict = (
                expected_msg.model_dump(exclude_none=True) if isinstance(expected_msg, BaseModel) else expected_msg
            )
            self.assertDictContainsSubset(msg_dict, output_msg, f"Message content mismatch at index {i}")

    @patch(
        "ee.hogai.hogql.nodes.HogQLNode.run",
        return_value=PartialAssistantState(
            messages=[AssistantMessage(content="Hello")],
        ),
    )
    def test_agent_responded(self, _mock_hogql_run):
        output = self._run_assistant_graph(
            HogQLGraph(self.team).compile_simple_graph(),
            conversation=self.conversation,
        )

        # Assert that ReasoningMessages are added
        expected_output = [
            (
                "message",
                HumanMessage(content="Hello").model_dump(exclude_none=True),
            ),
            (
                "message",
                AssistantMessage(content="Hello").model_dump(exclude_none=True),
            ),
        ]
        self.assertConversationEqual(output, expected_output)
