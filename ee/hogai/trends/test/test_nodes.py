from django.test import override_settings

from ee.hogai.trends.nodes import CreateTrendsPlanNode, GenerateTrendsNode
from posthog.schema import AssistantMessage, ExperimentalAITrendsQuery, HumanMessage, VisualizationMessage
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)


@override_settings(IN_UNIT_TESTING=True)
class TestPlanAgentNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self.schema = ExperimentalAITrendsQuery(series=[])

    def test_agent_reconstructs_conversation(self):
        node = CreateTrendsPlanNode(self.team)
        history = node._reconstruct_conversation({"messages": [HumanMessage(content="Text")]})
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn(f"{{question}}", history[0].content)

        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    VisualizationMessage(answer=self.schema, plan="randomplan"),
                ]
            }
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)
        self.assertEqual(history[1].type, "ai")
        self.assertEqual(history[1].content, "randomplan")

        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    VisualizationMessage(answer=self.schema, plan="randomplan"),
                    HumanMessage(content="Text"),
                ]
            }
        )
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)
        self.assertEqual(history[1].type, "ai")
        self.assertEqual(history[1].content, "randomplan")
        self.assertEqual(history[2].type, "human")
        self.assertIn("Text", history[2].content)
        self.assertNotIn("{{question}}", history[2].content)

    def test_agent_reconstructs_conversation_and_omits_unknown_messages(self):
        node = CreateTrendsPlanNode(self.team)
        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    AssistantMessage(content="test"),
                ]
            }
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)


@override_settings(IN_UNIT_TESTING=True)
class TestGenerateTrendsNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self.schema = ExperimentalAITrendsQuery(series=[])

    def test_agent_reconstructs_conversation(self):
        node = GenerateTrendsNode(self.team)
        history = node._reconstruct_conversation({"messages": [HumanMessage(content="Text")]})
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("Answer to this question:", history[1].content)
        self.assertNotIn("{{question}}", history[1].content)

        history = node._reconstruct_conversation({"messages": [HumanMessage(content="Text")], "plan": "randomplan"})
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("the plan", history[1].content)
        self.assertNotIn("{{plan}}", history[1].content)
        self.assertIn("randomplan", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Answer to this question:", history[2].content)
        self.assertNotIn("{{question}}", history[2].content)
        self.assertIn("Text", history[2].content)

        node = GenerateTrendsNode(self.team)
        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    VisualizationMessage(answer=self.schema, plan="randomplan"),
                    HumanMessage(content="Follow Up"),
                ],
                "plan": "newrandomplan",
            }
        )

        self.assertEqual(len(history), 6)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("the plan", history[1].content)
        self.assertNotIn("{{plan}}", history[1].content)
        self.assertIn("randomplan", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Answer to this question:", history[2].content)
        self.assertNotIn("{{question}}", history[2].content)
        self.assertIn("Text", history[2].content)
        self.assertEqual(history[3].type, "ai")
        self.assertEqual(history[3].content, self.schema.model_dump_json())
        self.assertEqual(history[4].type, "human")
        self.assertIn("the new plan", history[4].content)
        self.assertNotIn("{{plan}}", history[4].content)
        self.assertIn("newrandomplan", history[4].content)
        self.assertEqual(history[5].type, "human")
        self.assertIn("Answer to this question:", history[5].content)
        self.assertNotIn("{{question}}", history[5].content)
        self.assertIn("Follow Up", history[5].content)

    def test_agent_reconstructs_conversation_and_merges_messages(self):
        node = GenerateTrendsNode(self.team)
        history = node._reconstruct_conversation(
            {
                "messages": [HumanMessage(content="Te"), HumanMessage(content="xt")],
                "plan": "randomplan",
            }
        )
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("the plan", history[1].content)
        self.assertNotIn("{{plan}}", history[1].content)
        self.assertIn("randomplan", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Answer to this question:", history[2].content)
        self.assertNotIn("{{question}}", history[2].content)
        self.assertIn("Te\nxt", history[2].content)

        node = GenerateTrendsNode(self.team)
        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    VisualizationMessage(answer=self.schema, plan="randomplan"),
                    HumanMessage(content="Follow"),
                    HumanMessage(content="Up"),
                ],
                "plan": "newrandomplan",
            }
        )

        self.assertEqual(len(history), 6)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("the plan", history[1].content)
        self.assertNotIn("{{plan}}", history[1].content)
        self.assertIn("randomplan", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Answer to this question:", history[2].content)
        self.assertNotIn("{{question}}", history[2].content)
        self.assertIn("Text", history[2].content)
        self.assertEqual(history[3].type, "ai")
        self.assertEqual(history[3].content, self.schema.model_dump_json())
        self.assertEqual(history[4].type, "human")
        self.assertIn("the new plan", history[4].content)
        self.assertNotIn("{{plan}}", history[4].content)
        self.assertIn("newrandomplan", history[4].content)
        self.assertEqual(history[5].type, "human")
        self.assertIn("Answer to this question:", history[5].content)
        self.assertNotIn("{{question}}", history[5].content)
        self.assertIn("Follow\nUp", history[5].content)
