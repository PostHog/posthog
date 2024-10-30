from unittest.mock import patch

from django.test import override_settings
from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.trends.nodes import CreateTrendsPlanNode, GenerateTrendsNode
from ee.hogai.trends.parsers import AgentAction
from posthog.schema import AssistantMessage, ExperimentalAITrendsQuery, HumanMessage, VisualizationMessage
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person


@override_settings(IN_UNIT_TESTING=True)
class TestPlanAgentNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
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

    def test_agent_filters_out_low_count_events(self):
        _create_person(distinct_ids=["test"], team=self.team)
        for i in range(26):
            _create_event(event=f"event{i}", distinct_id="test", team=self.team)
            _create_event(event="distinctevent", distinct_id="test", team=self.team)
        node = CreateTrendsPlanNode(self.team)
        self.assertEqual(
            node._events_prompt,
            "<list of available events for filtering>\nall events\ndistinctevent\n</list of available events for filtering>",
        )

    def test_agent_preserves_low_count_events_for_smaller_teams(self):
        _create_person(distinct_ids=["test"], team=self.team)
        _create_event(event="distinctevent", distinct_id="test", team=self.team)
        node = CreateTrendsPlanNode(self.team)
        self.assertIn("distinctevent", node._events_prompt)
        self.assertIn("all events", node._events_prompt)

    def test_agent_scratchpad(self):
        node = CreateTrendsPlanNode(self.team)
        scratchpad = [
            (AgentAction(tool="test1", tool_input="input1", log="log1"), "test"),
            (AgentAction(tool="test2", tool_input="input2", log="log2"), None),
            (AgentAction(tool="test3", tool_input="input3", log="log3"), ""),
        ]
        prompt = node._get_agent_scratchpad(scratchpad)
        self.assertIn("log1", prompt)
        self.assertIn("log3", prompt)

    def test_agent_handles_output_without_action_block(self):
        with patch(
            "ee.hogai.trends.nodes.CreateTrendsPlanNode._model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="I don't want to output an action.")),
        ):
            node = CreateTrendsPlanNode(self.team)
            state_update = node.run({"messages": [HumanMessage(content="Question")]}, {})
            self.assertEqual(len(state_update["intermediate_steps"]), 1)
            action, obs = state_update["intermediate_steps"][0]
            self.assertIsNone(obs)
            self.assertIn("I don't want to output an action.", action.log)
            self.assertIn("Action:", action.log)
            self.assertIn("Action:", action.tool_input)

    def test_agent_handles_output_with_malformed_json(self):
        with patch(
            "ee.hogai.trends.nodes.CreateTrendsPlanNode._model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="Thought.\nAction: abc")),
        ):
            node = CreateTrendsPlanNode(self.team)
            state_update = node.run({"messages": [HumanMessage(content="Question")]}, {})
            self.assertEqual(len(state_update["intermediate_steps"]), 1)
            action, obs = state_update["intermediate_steps"][0]
            self.assertIsNone(obs)
            self.assertIn("Thought.\nAction: abc", action.log)
            self.assertIn("action", action.tool_input)
            self.assertIn("action_input", action.tool_input)


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
