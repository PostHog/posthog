import json
from collections.abc import Iterable
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from langchain_core.agents import AgentAction
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import AssistantMessage, AssistantTrendsQuery, FailureMessage, HumanMessage, VisualizationMessage

from ee.hogai.graph.schema_generator.nodes import (
    RETRIES_ALLOWED,
    SchemaGenerationException,
    SchemaGeneratorNode,
    SchemaGeneratorToolsNode,
)
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName, IntermediateStep
from ee.hogai.utils.types.composed import MaxNodeName

DummySchema = SchemaGeneratorOutput[AssistantTrendsQuery]


class DummyGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    INSIGHT_NAME = "Test"
    OUTPUT_MODEL = SchemaGeneratorOutput[AssistantTrendsQuery]
    OUTPUT_SCHEMA = {}

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.TRENDS_GENERATOR

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "system_prompt"),
            ],
        )
        return await super()._run_with_prompt(state, prompt, config=config)


@override_settings(IN_UNIT_TESTING=True)
class TestSchemaGeneratorNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.basic_trends = AssistantTrendsQuery(series=[])

    async def test_node_runs(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: DummySchema(query=self.basic_trends).model_dump()
            )
            new_state = await node.arun(
                AssistantState(
                    messages=[HumanMessage(content="Text", id="0")],
                    plan="Plan",
                    start_id="0",
                ),
                {},
            )
            self.assertEqual(new_state.intermediate_steps, None)
            self.assertEqual(new_state.plan, None)
            self.assertEqual(len(new_state.messages), 1)
            self.assertEqual(new_state.messages[0].type, "ai/viz")
            self.assertEqual(cast(VisualizationMessage, new_state.messages[0]).answer, self.basic_trends)

    async def test_agent_reconstructs_conversation_and_does_not_add_an_empty_plan(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(messages=[HumanMessage(content="Text", id="0")], start_id="0")
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("Answer to this question:", history[1].content)
        self.assertNotIn("{{question}}", history[1].content)

    async def test_agent_reconstructs_conversation_adds_plan(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(
                messages=[HumanMessage(content="Text", id="0")],
                plan="randomplan",
                start_id="0",
                root_tool_insight_plan="Text",
            )
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

    async def test_agent_reconstructs_conversation_can_handle_follow_ups(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Multiple questions", id="0"),
                    VisualizationMessage(
                        answer=self.basic_trends, plan="randomplan", id="1", initiator="0", query="Query"
                    ),
                    HumanMessage(content="Follow Up", id="2"),
                ],
                plan="newrandomplan",
                start_id="2",
            )
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
        self.assertIn("Query", history[2].content)
        self.assertEqual(history[3].type, "ai")
        self.assertEqual(history[3].content, self.basic_trends.model_dump_json())
        self.assertEqual(history[4].type, "human")
        self.assertIn("the new plan", history[4].content)
        self.assertNotIn("{{plan}}", history[4].content)
        self.assertIn("newrandomplan", history[4].content)
        self.assertEqual(history[5].type, "human")
        self.assertIn("Answer to this question:", history[5].content)
        self.assertNotIn("{{question}}", history[5].content)
        self.assertIn("Follow Up", history[5].content)

    async def test_agent_reconstructs_typical_conversation(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Question 1", id="0"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[]), plan="Plan 1", initiator="0", id="2", query="Query 1"
                    ),
                    AssistantMessage(content="Summary 1", id="3"),
                    HumanMessage(content="Question 2", id="4"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[]), plan="Plan 2", initiator="4", id="6", query="Query 2"
                    ),
                    AssistantMessage(content="Summary 2", id="7"),
                    HumanMessage(content="Question 3", id="8"),
                ],
                plan="Plan 3",
                start_id="8",
                root_tool_insight_plan="Query 3",
            )
        )

        self.assertEqual(len(history), 9)
        self.assertEqual(history[0].type, "human")
        self.assertIn("mapping", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("Plan 1", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Query 1", history[2].content)
        self.assertEqual(history[3].type, "ai")
        AssistantTrendsQuery.model_validate_json(cast(str, history[3].content))
        self.assertEqual(history[4].type, "human")
        self.assertIn("Plan 2", history[4].content)
        self.assertEqual(history[5].type, "human")
        self.assertIn("Query 2", history[5].content)
        self.assertEqual(history[6].type, "ai")
        AssistantTrendsQuery.model_validate_json(cast(str, history[6].content))
        self.assertEqual(history[7].type, "human")
        self.assertIn("Plan 3", history[7].content)
        self.assertEqual(history[8].type, "human")
        self.assertIn("Query 3", history[8].content)

    async def test_prompt_messages_merged(self):
        node = DummyGeneratorNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="Question 1", id="0"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1", initiator="0", id="2"),
                AssistantMessage(content="Summary 1", id="3"),
                HumanMessage(content="Question 2", id="4"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2", initiator="4", id="6"),
                AssistantMessage(content="Summary 2", id="7"),
                HumanMessage(content="Question 3", id="8"),
            ],
            plan="Plan 3",
            start_id="8",
        )
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:

            def assert_prompt(prompt):
                self.assertEqual(len(prompt), 6)
                self.assertEqual(prompt[0].type, "system")
                self.assertEqual(prompt[1].type, "human")
                self.assertEqual(prompt[2].type, "ai")
                self.assertEqual(prompt[3].type, "human")
                self.assertEqual(prompt[4].type, "ai")
                self.assertEqual(prompt[5].type, "human")

            generator_model_mock.return_value = RunnableLambda(assert_prompt)
            await node.arun(state, {})

    async def test_failover_with_malformed_query(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            # Emulate an incorrect JSON - it should be an object, but let's make it a list here
            output = DummySchema.model_construct(query=[]).model_dump()  # type: ignore
            generator_model_mock.return_value = RunnableLambda(lambda _: json.dumps(output))

            new_state = await node.arun(AssistantState(messages=[HumanMessage(content="Text")]), {})
            new_state = cast(PartialAssistantState, new_state)
            self.assertEqual(len(new_state.intermediate_steps or []), 1)

            new_state = await node.arun(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    intermediate_steps=[(AgentAction(tool="", tool_input="", log="exception"), "exception")],
                ),
                {},
            )
            self.assertEqual(len(new_state.intermediate_steps or []), 2)

    async def test_quality_check_failure_with_retries_available(self):
        """Test quality check failure triggering retry when retries are available."""
        node = DummyGeneratorNode(self.team, self.user)
        with (
            patch.object(DummyGeneratorNode, "_model") as generator_model_mock,
            patch.object(DummyGeneratorNode, "_quality_check_output") as quality_check_mock,
        ):
            valid_output = DummySchema(query=self.basic_trends).model_dump()
            generator_model_mock.return_value = RunnableLambda(lambda _: valid_output)

            quality_check_mock.side_effect = PydanticOutputParserException(
                llm_output="SELECT x FROM events", validation_message="Field validation failed"
            )

            new_state = await node.arun(
                AssistantState(messages=[HumanMessage(content="Text", id="0")], start_id="0"), {}
            )
            new_state = cast(PartialAssistantState, new_state)

            # Should trigger retry
            self.assertEqual(len(new_state.intermediate_steps or []), 1)
            action, _ = cast(list[IntermediateStep], new_state.intermediate_steps)[0]
            self.assertEqual(action.tool, "handle_incorrect_response")
            self.assertEqual(action.tool_input, "SELECT x FROM events")
            self.assertEqual(action.log, "Field validation failed")

    async def test_quality_check_failure_with_retries_exhausted(self):
        """Test quality check failure with retries exhausted raises SchemaGenerationException."""
        node = DummyGeneratorNode(self.team, self.user)
        with (
            patch.object(DummyGeneratorNode, "_model") as generator_model_mock,
            patch.object(DummyGeneratorNode, "_quality_check_output") as quality_check_mock,
        ):
            valid_output = DummySchema(query=self.basic_trends).model_dump()
            generator_model_mock.return_value = RunnableLambda(lambda _: valid_output)

            # Quality check always fails
            quality_check_mock.side_effect = PydanticOutputParserException(
                llm_output='{"query": "test"}', validation_message="Quality check failed"
            )

            # Start with RETRIES_ALLOWED intermediate steps (so no more allowed)
            with self.assertRaises(SchemaGenerationException) as cm:
                await node.arun(
                    AssistantState(
                        messages=[HumanMessage(content="Text", id="0")],
                        start_id="0",
                        intermediate_steps=cast(
                            list[IntermediateStep],
                            [
                                (AgentAction(tool="handle_incorrect_response", tool_input="", log=""), "retry"),
                            ],
                        )
                        * RETRIES_ALLOWED,
                    ),
                    {},
                )

            # Verify the exception contains the expected information
            self.assertEqual(cm.exception.llm_output, '{"query": "test"}')
            self.assertEqual(cm.exception.validation_message, "Quality check failed")

    async def test_node_leaves_failover(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(
            DummyGeneratorNode,
            "_model",
            return_value=RunnableLambda(lambda _: DummySchema(query=self.basic_trends).model_dump()),
        ):
            new_state = await node.arun(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    intermediate_steps=[(AgentAction(tool="", tool_input="", log="exception"), "exception")],
                ),
                {},
            )
            self.assertEqual(new_state.intermediate_steps, None)

            new_state = await node.arun(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    intermediate_steps=[
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                    ],
                ),
                {},
            )
            self.assertEqual(new_state.intermediate_steps, None)

    async def test_node_leaves_failover_after_second_unsuccessful_attempt(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            # Emulate an incorrect JSON - it should be an object, but let's make it a list here
            schema = DummySchema.model_construct(query=[]).model_dump()  # type: ignore
            generator_model_mock.return_value = RunnableLambda(lambda _: json.dumps(schema))

            with self.assertRaises(SchemaGenerationException):
                await node.arun(
                    AssistantState(
                        messages=[HumanMessage(content="Text")],
                        intermediate_steps=[
                            (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                            (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                        ],
                    ),
                    {},
                )

    async def test_agent_reconstructs_conversation_with_failover(self):
        action = AgentAction(tool="fix", tool_input="validation error", log="exception")
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(
                messages=[HumanMessage(content="Text", id="0")],
                plan="randomplan",
                intermediate_steps=[(action, "uniqexception")],
                start_id="0",
            ),
            validation_error_message="uniqexception",
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

    async def test_agent_reconstructs_conversation_with_failed_messages(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Text"),
                    FailureMessage(content="Error"),
                    HumanMessage(content="Text"),
                ],
                plan="randomplan",
            ),
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
        node = DummyGeneratorNode(self.team, self.user)
        state = node.router(AssistantState(messages=[], intermediate_steps=None))
        self.assertEqual(state, "next")
        state = node.router(
            AssistantState(messages=[], intermediate_steps=[(AgentAction(tool="", tool_input="", log=""), None)])
        )
        self.assertEqual(state, "tools")

    async def test_injects_insight_description(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(
                messages=[HumanMessage(content="Text", id="0")],
                start_id="0",
                root_tool_insight_plan="Foobar",
                root_tool_insight_type="trends",
            )
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "human")
        self.assertIn("group", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("Foobar", history[1].content)
        self.assertNotIn("{{question}}", history[1].content)

    async def test_injects_insight_description_and_keeps_original_question(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Original question", id="1"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[]), plan="Plan 1", initiator="1", id="2", query="Query 1"
                    ),
                    HumanMessage(content="Second question", id="3"),
                ],
                start_id="3",
                root_tool_insight_plan="Foobar",
                root_tool_insight_type="trends",
            )
        )
        self.assertEqual(len(history), 5)
        self.assertEqual(history[0].type, "human")
        self.assertIn("group", history[0].content)
        self.assertEqual(history[1].type, "human")
        self.assertIn("Plan 1", history[1].content)
        self.assertNotIn("{{question}}", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Query 1", history[2].content)
        self.assertNotIn("{{question}}", history[2].content)
        self.assertEqual(history[3].type, "ai")
        self.assertEqual(history[4].type, "human")
        self.assertIn("Foobar", history[4].content)
        self.assertNotIn("{{question}}", history[4].content)

    async def test_keeps_maximum_number_of_viz_messages(self):
        node = DummyGeneratorNode(self.team, self.user)
        query = AssistantTrendsQuery(series=[])
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    VisualizationMessage(query="Query 1", answer=query, plan="Plan 1", id="1"),
                    VisualizationMessage(query="Query 2", answer=query, plan="Plan 2", id="2"),
                    VisualizationMessage(query="Query 3", answer=query, plan="Plan 3", id="3"),
                    VisualizationMessage(query="Query 4", answer=query, plan="Plan 4", id="4"),
                    VisualizationMessage(query="Query 5", answer=query, plan="Plan 5", id="5"),
                    VisualizationMessage(query="Query 6", answer=query, plan="Plan 6", id="6"),
                    VisualizationMessage(query="Query 7", answer=query, plan="Plan 7", id="7"),
                ],
                root_tool_insight_plan="Query 8",
                root_tool_insight_type="trends",
            )
        )
        self.assertEqual(len(history), 17)
        self.assertEqual(history[0].type, "human")
        self.assertIn("group", history[0].content)

        # Query 3
        self.assertEqual(history[1].type, "human")
        self.assertIn("Plan 3", history[1].content)
        self.assertEqual(history[2].type, "human")
        self.assertIn("Query 3", history[2].content)
        self.assertEqual(history[3].type, "ai")

        # Query 4
        self.assertEqual(history[4].type, "human")
        self.assertIn("Plan 4", history[4].content)
        self.assertEqual(history[5].type, "human")
        self.assertIn("Query 4", history[5].content)
        self.assertEqual(history[6].type, "ai")

        # Query 5
        self.assertEqual(history[7].type, "human")
        self.assertIn("Plan 5", history[7].content)
        self.assertEqual(history[8].type, "human")
        self.assertIn("Query 5", history[8].content)
        self.assertEqual(history[9].type, "ai")

        # Query 6
        self.assertEqual(history[10].type, "human")
        self.assertIn("Plan 6", history[10].content)
        self.assertEqual(history[11].type, "human")
        self.assertIn("Query 6", history[11].content)
        self.assertEqual(history[12].type, "ai")

        # Query 7
        self.assertEqual(history[13].type, "human")
        self.assertIn("Plan 7", history[13].content)
        self.assertEqual(history[14].type, "human")
        self.assertIn("Query 7", history[14].content)
        self.assertEqual(history[15].type, "ai")

        # New query
        self.assertEqual(history[16].type, "human")
        self.assertIn("Query 8", history[16].content)

    async def test_agent_handles_incomplete_json(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(
            DummyGeneratorNode,
            "_model",
            return_value=RunnableLambda(
                lambda _: """\n\n{\"query\":{\"kind\":\"RetentionQuery\",\"dateRange\":{\"date_from\":\"2024-01-01\",\"date_to\":\"2024-12-31\"},\"retentionFilter\":{\"period\":\"Week\",\"totalIntervals\":11,\"targetEntity\":{\"name\":\"Application Opened\",\"type\":\"events\"},\"returningEntity\":{\"name\":\"Application Opened\",\"type\":\"events\"}},\"filterTestAccounts\":false}\t \t\t \t\t \t \t"""
            ),
        ):
            new_state = await node.arun(AssistantState(messages=[HumanMessage(content="Text")]), {})
            self.assertEqual(len(new_state.intermediate_steps or []), 1)


class MockSchemaGeneratorToolsNode(SchemaGeneratorToolsNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.TRENDS_GENERATOR_TOOLS


class TestSchemaGeneratorToolsNode(BaseTest):
    async def test_tools_node(self):
        node = MockSchemaGeneratorToolsNode(self.team, self.user)
        action = AgentAction(tool="fix", tool_input="validationerror", log="pydanticexception")
        state = await node.arun(AssistantState(messages=[], intermediate_steps=[(action, None)]), {})
        state = cast(PartialAssistantState, state)
        self.assertIsNotNone("validationerror", cast(list[IntermediateStep], state.intermediate_steps)[0][1])
        self.assertIn(
            "validationerror", cast(Iterable[Any], cast(list[IntermediateStep], state.intermediate_steps)[0][1])
        )
        self.assertIn(
            "pydanticexception", cast(Iterable[Any], cast(list[IntermediateStep], state.intermediate_steps)[0][1])
        )
