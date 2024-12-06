import json
from unittest.mock import patch

from django.test import override_settings
from langchain_core.agents import AgentAction
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ee.hogai.schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ee.hogai.schema_generator.utils import SchemaGeneratorOutput
from posthog.schema import (
    AssistantMessage,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    RouterMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

TestSchema = SchemaGeneratorOutput[AssistantTrendsQuery]


class DummyGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    INSIGHT_NAME = "Test"
    OUTPUT_MODEL = SchemaGeneratorOutput[AssistantTrendsQuery]
    OUTPUT_SCHEMA = {}

    def run(self, state, config):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "system_prompt"),
            ],
        )
        return super()._run_with_prompt(state, prompt, config=config)


@override_settings(IN_UNIT_TESTING=True)
class TestSchemaGeneratorNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self.schema = AssistantTrendsQuery(series=[])

    def test_node_runs(self):
        node = DummyGeneratorNode(self.team)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(lambda _: TestSchema(query=self.schema).model_dump())
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
                    "messages": [VisualizationMessage(answer=self.schema, plan="Plan", done=True)],
                    "intermediate_steps": None,
                },
            )

    def test_agent_reconstructs_conversation(self):
        node = DummyGeneratorNode(self.team)
        history = node._construct_messages({"messages": [HumanMessage(content="Text")]})
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("Answer to this question:", history[1].content)
        self.assertNotIn("{{question}}", history[1].content)

        history = node._construct_messages({"messages": [HumanMessage(content="Text")], "plan": "randomplan"})
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

        node = DummyGeneratorNode(self.team)
        history = node._construct_messages(
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
        node = DummyGeneratorNode(self.team)
        history = node._construct_messages(
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

        node = DummyGeneratorNode(self.team)
        history = node._construct_messages(
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

    def test_agent_reconstructs_typical_conversation(self):
        node = DummyGeneratorNode(self.team)
        history = node._construct_messages(
            {
                "messages": [
                    HumanMessage(content="Question 1"),
                    RouterMessage(content="trends"),
                    VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1"),
                    AssistantMessage(content="Summary 1"),
                    HumanMessage(content="Question 2"),
                    RouterMessage(content="funnel"),
                    VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2"),
                    AssistantMessage(content="Summary 2"),
                    HumanMessage(content="Question 3"),
                    RouterMessage(content="funnel"),
                ],
                "plan": "Plan 3",
            }
        )
        self.assertEqual(len(history), 8)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("Plan 1", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Question 1", history[2].content)
        self.assertEqual(history[3].type, "human")
        self.assertIn("Plan 2", history[3].content)
        self.assertEqual(history[4].type, "human")
        self.assertIn("Question 2", history[4].content)
        self.assertEqual(history[5].type, "ai")
        self.assertEqual(history[6].type, "human")
        self.assertIn("Plan 3", history[6].content)
        self.assertEqual(history[7].type, "human")
        self.assertIn("Question 3", history[7].content)

    def test_prompt(self):
        node = DummyGeneratorNode(self.team)
        state = {
            "messages": [
                HumanMessage(content="Question 1"),
                RouterMessage(content="trends"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1"),
                AssistantMessage(content="Summary 1"),
                HumanMessage(content="Question 2"),
                RouterMessage(content="funnel"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2"),
                AssistantMessage(content="Summary 2"),
                HumanMessage(content="Question 3"),
                RouterMessage(content="funnel"),
            ],
            "plan": "Plan 3",
        }
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:

            def assert_prompt(prompt):
                self.assertEqual(len(prompt), 4)
                self.assertEqual(prompt[0].type, "system")
                self.assertEqual(prompt[1].type, "human")
                self.assertEqual(prompt[2].type, "ai")
                self.assertEqual(prompt[3].type, "human")

            generator_model_mock.return_value = RunnableLambda(assert_prompt)
            node.run(state, {})

    def test_failover_with_incorrect_schema(self):
        node = DummyGeneratorNode(self.team)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            schema = TestSchema(query=None).model_dump()
            # Emulate an incorrect JSON. It should be an object.
            schema["query"] = []
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
        node = DummyGeneratorNode(self.team)
        with patch.object(
            DummyGeneratorNode,
            "_model",
            return_value=RunnableLambda(lambda _: TestSchema(query=self.schema).model_dump()),
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
        node = DummyGeneratorNode(self.team)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            schema = TestSchema(query=None).model_dump()
            # Emulate an incorrect JSON. It should be an object.
            schema["query"] = []
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
        node = DummyGeneratorNode(self.team)
        history = node._construct_messages(
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

    def test_agent_reconstructs_conversation_with_failed_messages(self):
        node = DummyGeneratorNode(self.team)
        history = node._construct_messages(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    FailureMessage(content="Error"),
                    HumanMessage(content="Text"),
                ],
                "plan": "randomplan",
            },
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
        self.assertIn("Text", history[2].content)

    def test_router(self):
        node = DummyGeneratorNode(self.team)
        state = node.router({"messages": [], "intermediate_steps": None})
        self.assertEqual(state, "next")
        state = node.router(
            {"messages": [], "intermediate_steps": [(AgentAction(tool="", tool_input="", log=""), None)]}
        )
        self.assertEqual(state, "tools")


class TestSchemaGeneratorToolsNode(ClickhouseTestMixin, APIBaseTest):
    def test_tools_node(self):
        node = SchemaGeneratorToolsNode(self.team)
        action = AgentAction(tool="fix", tool_input="validationerror", log="pydanticexception")
        state = node.run({"messages": [], "intermediate_steps": [(action, None)]}, {})
        self.assertIsNotNone("validationerror", state["intermediate_steps"][0][1])
        self.assertIn("validationerror", state["intermediate_steps"][0][1])
        self.assertIn("pydanticexception", state["intermediate_steps"][0][1])
