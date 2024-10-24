import json
from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda

from ee.hogai.assistant import Assistant
from ee.hogai.trends.utils import GenerateTrendOutputModel
from ee.hogai.utils import Conversation
from posthog.schema import HumanMessage, VisualizationMessage
from posthog.test.base import (
    NonAtomicBaseTest,
)


@override_settings(IN_UNIT_TESTING=True)
class TestAssistant(NonAtomicBaseTest):
    def test_assistant(self):
        mocked_planner_response = """
        Action:
        ```
        {"action": "final_answer", "action_input": "Plan"}
        ```
        """
        generator_response = GenerateTrendOutputModel(reasoning_steps=[], answer=None)
        with (
            patch(
                "ee.hogai.trends.nodes.CreateTrendsPlanNode._model",
                return_value=RunnableLambda(lambda _: mocked_planner_response),
            ) as planner_model_mock,
            patch(
                "ee.hogai.trends.nodes.GenerateTrendsNode._model",
                return_value=RunnableLambda(lambda _: generator_response.model_dump()),
            ) as generator_model_mock,
        ):
            assistant = Assistant(self.team)
            generator = assistant.stream(
                Conversation(messages=[HumanMessage(content="Launch the chain.")], session_id="id")
            )
            self.assertEqual(
                json.loads(next(generator)),
                VisualizationMessage(answer=generator_response.model_dump_json(), plan="Plan").model_dump(),
            )
            self.assertEqual(planner_model_mock.call_count, 1)
            self.assertEqual(generator_model_mock.call_count, 1)
