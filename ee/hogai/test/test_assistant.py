import json
from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda

from ee.hogai.assistant import Assistant
from ee.hogai.trends.utils import GenerateTrendOutputModel
from ee.hogai.utils import AssistantMessage as AssistantMessageSchema
from posthog.schema import AssistantMessage, VisualizationMessagePayload
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
            generator = assistant.stream(messages=[AssistantMessageSchema(content="Launch the chain.", type="human")])
            self.assertEqual(
                json.loads(next(generator)),
                AssistantMessage(
                    content=generator_response.model_dump_json(),
                    type="ai",
                    payload=VisualizationMessagePayload(plan="Plan"),
                ).model_dump(),
            )
            self.assertEqual(planner_model_mock.call_count, 1)
            self.assertEqual(generator_model_mock.call_count, 1)
