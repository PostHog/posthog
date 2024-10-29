import json
from unittest.mock import patch

from django.test import override_settings
from langchain_core.agents import AgentAction
from langchain_core.runnables import RunnableLambda

from ee.hogai.trends.nodes import CreateTrendsPlanNode, GenerateTrendsNode, GenerateTrendsToolsNode
from ee.hogai.trends.utils import GenerateTrendOutputModel
from ee.hogai.utils import AssistantNodeName
from posthog.schema import (
    AssistantMessage,
    ExperimentalAITrendsQuery,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)
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


@override_settings(IN_UNIT_TESTING=True)
class TestGenerateTrendsNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self.schema = ExperimentalAITrendsQuery(series=[])

    def test_node_runs(self):
        node = GenerateTrendsNode(self.team)
        with patch("ee.hogai.trends.nodes.GenerateTrendsNode._model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: GenerateTrendOutputModel(reasoning_steps=["step"], answer=self.schema).model_dump()
            )
            new_state = node.run(
                {
                    "messages": [HumanMessage(content="Text")],
                    "plan": "Plan",
                },
                {},
            )
            self.assertEqual(
                new_state,
                {
                    "messages": [VisualizationMessage(answer=self.schema, plan="Plan", reasoning_steps=["step"])],
                    "intermediate_steps": None,
                },
            )

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

    def test_failover_with_incorrect_schema(self):
        node = GenerateTrendsNode(self.team)
        with patch("ee.hogai.trends.nodes.GenerateTrendsNode._model") as generator_model_mock:
            schema = GenerateTrendOutputModel(reasoning_steps=[], answer=None).model_dump()
            # Emulate an incorrect JSON. It should be an object.
            schema["answer"] = []
            generator_model_mock.return_value = RunnableLambda(lambda _: json.dumps(schema))

            new_state = node.run({"messages": [HumanMessage(content="Text")]}, {})
            self.assertIn("intermediate_steps", new_state)
            self.assertEqual(len(new_state["intermediate_steps"]), 1)

            new_state = node.run(
                {
                    "messages": [HumanMessage(content="Text")],
                    "intermediate_steps": [(AgentAction(tool="", tool_input="", log="exception"), "exception")],
                },
                {},
            )
            self.assertIn("intermediate_steps", new_state)
            self.assertEqual(len(new_state["intermediate_steps"]), 2)

    def test_node_leaves_failover(self):
        node = GenerateTrendsNode(self.team)
        with patch(
            "ee.hogai.trends.nodes.GenerateTrendsNode._model",
            return_value=RunnableLambda(
                lambda _: GenerateTrendOutputModel(reasoning_steps=[], answer=self.schema).model_dump()
            ),
        ):
            new_state = node.run(
                {
                    "messages": [HumanMessage(content="Text")],
                    "intermediate_steps": [(AgentAction(tool="", tool_input="", log="exception"), "exception")],
                },
                {},
            )
            self.assertIsNone(new_state["intermediate_steps"])

            new_state = node.run(
                {
                    "messages": [HumanMessage(content="Text")],
                    "intermediate_steps": [
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                    ],
                },
                {},
            )
            self.assertIsNone(new_state["intermediate_steps"])

    def test_node_leaves_failover_after_second_unsuccessful_attempt(self):
        node = GenerateTrendsNode(self.team)
        with patch("ee.hogai.trends.nodes.GenerateTrendsNode._model") as generator_model_mock:
            schema = GenerateTrendOutputModel(reasoning_steps=[], answer=None).model_dump()
            # Emulate an incorrect JSON. It should be an object.
            schema["answer"] = []
            generator_model_mock.return_value = RunnableLambda(lambda _: json.dumps(schema))

            new_state = node.run(
                {
                    "messages": [HumanMessage(content="Text")],
                    "intermediate_steps": [
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                    ],
                },
                {},
            )
            self.assertIsNone(new_state["intermediate_steps"])
            self.assertEqual(len(new_state["messages"]), 1)
            self.assertIsInstance(new_state["messages"][0], FailureMessage)

    def test_agent_reconstructs_conversation_with_failover(self):
        action = AgentAction(tool="fix", tool_input="validation error", log="exception")
        node = GenerateTrendsNode(self.team)
        history = node._reconstruct_conversation(
            {
                "messages": [HumanMessage(content="Text")],
                "plan": "randomplan",
                "intermediate_steps": [(action, "uniqexception")],
            },
            "uniqexception",
        )
        self.assertEqual(len(history), 4)
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
        self.assertEqual(history[3].type, "human")
        self.assertIn("Pydantic", history[3].content)
        self.assertIn("uniqexception", history[3].content)

    def test_router(self):
        node = GenerateTrendsNode(self.team)
        state = node.router({"messages": [], "intermediate_steps": None})
        self.assertEqual(state, AssistantNodeName.END)
        state = node.router(
            {"messages": [], "intermediate_steps": [(AgentAction(tool="", tool_input="", log=""), None)]}
        )
        self.assertEqual(state, AssistantNodeName.GENERATE_TRENDS_TOOLS)


class TestGenerateTrendsToolsNode(ClickhouseTestMixin, APIBaseTest):
    def test_tools_node(self):
        node = GenerateTrendsToolsNode(self.team)
        action = AgentAction(tool="fix", tool_input="validationerror", log="pydanticexception")
        state = node.run({"messages": [], "intermediate_steps": [(action, None)]}, {})
        self.assertIsNotNone("validationerror", state["intermediate_steps"][0][1])
        self.assertIn("validationerror", state["intermediate_steps"][0][1])
        self.assertIn("pydanticexception", state["intermediate_steps"][0][1])
