import json
from collections.abc import Iterable
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from langchain_core.agents import AgentAction
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantTrendsQuery,
    HumanMessage,
    VisualizationArtifactContent,
)

from products.posthog_ai.backend.models.assistant import AgentArtifact, Conversation

from ee.hogai.chat_agent.schema_generator.nodes import (
    RETRIES_ALLOWED,
    SchemaGenerationException,
    SchemaGeneratorNode,
    SchemaGeneratorToolsNode,
)
from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.chat_agent.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage, IntermediateStep

DummySchema = SchemaGeneratorOutput[AssistantTrendsQuery]


class DummyGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    INSIGHT_NAME = "Test"
    OUTPUT_MODEL = SchemaGeneratorOutput[AssistantTrendsQuery]
    OUTPUT_SCHEMA = {}

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
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    async def test_node_runs(self):
        node = DummyGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": self.conversation.id})
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: DummySchema(
                    query=self.basic_trends, name="Test Query Name", description="Test Query Description"
                ).model_dump()
            )
            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text", id="0")],
                    plan="Plan",
                    start_id="0",
                ),
                config,
            )
            assert new_state is not None
            assert new_state.intermediate_steps is None
            assert new_state.plan is None
            assert len(new_state.messages) == 1
            assert isinstance(new_state.messages[0], ArtifactRefMessage)
            assert cast(ArtifactRefMessage, new_state.messages[0]).content_type == ArtifactContentType.VISUALIZATION
            assert cast(ArtifactRefMessage, new_state.messages[0]).source == ArtifactSource.ARTIFACT
            assert cast(ArtifactRefMessage, new_state.messages[0]).artifact_id is not None

    async def test_node_sets_name_description_and_plan_in_artifact(self):
        node = DummyGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": self.conversation.id})
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: DummySchema(
                    query=self.basic_trends,
                ).model_dump()
            )
            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text", id="0")],
                    plan="Test Plan Content",
                    visualization_title="Test Query Name",
                    visualization_description="Test Query Description",
                    start_id="0",
                ),
                config,
            )
            assert new_state is not None
            assert len(new_state.messages) == 1
            artifact_message = cast(ArtifactRefMessage, new_state.messages[0])

            artifact = await AgentArtifact.objects.aget(short_id=artifact_message.artifact_id)
            content = VisualizationArtifactContent.model_validate(artifact.data)

            assert content.name == "Test Query Name"
            assert content.description == "Test Query Description"
            assert content.plan == "Test Plan Content"

    async def test_node_sets_empty_plan_when_no_plan_in_state(self):
        node = DummyGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": self.conversation.id})
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: DummySchema(
                    query=self.basic_trends,
                ).model_dump()
            )
            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text", id="0")],
                    plan=None,
                    visualization_title="Query Name",
                    visualization_description="Description",
                    start_id="0",
                ),
                config,
            )
            assert new_state is not None
            artifact_message = cast(ArtifactRefMessage, new_state.messages[0])

            artifact = await AgentArtifact.objects.aget(short_id=artifact_message.artifact_id)
            content = VisualizationArtifactContent.model_validate(artifact.data)

            assert content.name == "Query Name"
            assert content.description == "Description"
            assert content.plan == ""

    async def test_construct_messages_includes_group_mapping_and_plan(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(messages=[HumanMessage(content="Text", id="0")], plan="randomplan", start_id="0")
        )
        assert len(history) == 2
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "the plan" in history[1].content
        assert "randomplan" in history[1].content
        assert "Generate a schema" in history[1].content

    async def test_construct_messages_with_empty_plan(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(messages=[HumanMessage(content="Text", id="0")], start_id="0")
        )
        assert len(history) == 2
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "Generate a schema" in history[1].content

    async def test_prompt_messages_merged(self):
        node = DummyGeneratorNode(self.team, self.user)
        state = AssistantState(
            messages=[HumanMessage(content="Question", id="0")],
            plan="Plan",
            start_id="0",
        )
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:

            def assert_prompt(prompt):
                # System prompt + merged human messages (group mapping + plan)
                assert len(prompt) == 2
                assert prompt[0].type == "system"
                assert prompt[1].type == "human"

            generator_model_mock.return_value = RunnableLambda(assert_prompt)
            await node(state, {})

    async def test_failover_with_malformed_query(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            # Emulate an incorrect JSON - it should be an object, but let's make it a list here
            output = DummySchema.model_construct(query=[]).model_dump()  # type: ignore
            generator_model_mock.return_value = RunnableLambda(lambda _: json.dumps(output))

            new_state = await node(AssistantState(messages=[HumanMessage(content="Text")]), {})
            new_state = cast(PartialAssistantState, new_state)
            assert len(new_state.intermediate_steps or []) == 1

            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    intermediate_steps=[(AgentAction(tool="", tool_input="", log="exception"), "exception")],
                ),
                {},
            )
            assert new_state is not None
            assert len(new_state.intermediate_steps or []) == 2

    async def test_quality_check_failure_with_retries_available(self):
        """Test quality check failure triggering retry when retries are available."""
        node = DummyGeneratorNode(self.team, self.user)
        with (
            patch.object(DummyGeneratorNode, "_model") as generator_model_mock,
            patch.object(DummyGeneratorNode, "_quality_check_output") as quality_check_mock,
        ):
            valid_output = DummySchema(
                query=self.basic_trends, name="Test Query Name", description="Test Query Description"
            ).model_dump()
            generator_model_mock.return_value = RunnableLambda(lambda _: valid_output)

            quality_check_mock.side_effect = PydanticOutputParserException(
                llm_output="SELECT x FROM events", validation_message="Field validation failed"
            )

            new_state = await node(AssistantState(messages=[HumanMessage(content="Text", id="0")], start_id="0"), {})
            new_state = cast(PartialAssistantState, new_state)

            # Should trigger retry
            assert len(new_state.intermediate_steps or []) == 1
            action, _ = cast(list[IntermediateStep], new_state.intermediate_steps)[0]
            assert action.tool == "handle_incorrect_response"
            assert action.tool_input == "SELECT x FROM events"
            assert action.log == "Field validation failed"

    async def test_quality_check_failure_with_retries_exhausted(self):
        """Test quality check failure with retries exhausted raises SchemaGenerationException."""
        node = DummyGeneratorNode(self.team, self.user)
        with (
            patch.object(DummyGeneratorNode, "_model") as generator_model_mock,
            patch.object(DummyGeneratorNode, "_quality_check_output") as quality_check_mock,
        ):
            valid_output = DummySchema(
                query=self.basic_trends, name="Test Query Name", description="Test Query Description"
            ).model_dump()
            generator_model_mock.return_value = RunnableLambda(lambda _: valid_output)

            # Quality check always fails
            quality_check_mock.side_effect = PydanticOutputParserException(
                llm_output='{"query": "test"}', validation_message="Quality check failed"
            )

            # Start with RETRIES_ALLOWED intermediate steps (so no more allowed)
            with self.assertRaises(SchemaGenerationException) as cm:
                await node(
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
            assert cm.exception.llm_output == '{"query": "test"}'
            assert cm.exception.validation_message == "Quality check failed"

    async def test_node_leaves_failover(self):
        node = DummyGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": self.conversation.id})
        with patch.object(
            DummyGeneratorNode,
            "_model",
            return_value=RunnableLambda(
                lambda _: DummySchema(
                    query=self.basic_trends, name="Test Query Name", description="Test Query Description"
                ).model_dump()
            ),
        ):
            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    intermediate_steps=[(AgentAction(tool="", tool_input="", log="exception"), "exception")],
                ),
                config,
            )
            assert new_state is not None
            assert new_state.intermediate_steps is None

            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    intermediate_steps=[
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                        (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                    ],
                ),
                config,
            )
            assert new_state is not None
            assert new_state.intermediate_steps is None

    async def test_node_leaves_failover_after_second_unsuccessful_attempt(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:
            # Emulate an incorrect JSON - it should be an object, but let's make it a list here
            schema = DummySchema.model_construct(query=[]).model_dump()  # type: ignore
            generator_model_mock.return_value = RunnableLambda(lambda _: json.dumps(schema))

            with self.assertRaises(SchemaGenerationException):
                await node(
                    AssistantState(
                        messages=[HumanMessage(content="Text")],
                        intermediate_steps=[
                            (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                            (AgentAction(tool="", tool_input="", log="exception"), "exception"),
                        ],
                    ),
                    {},
                )

    async def test_construct_messages_with_failover(self):
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
        assert len(history) == 3
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "the plan" in history[1].content
        assert "randomplan" in history[1].content
        assert history[2].type == "human"
        assert "Pydantic" in history[2].content
        assert "uniqexception" in history[2].content

    def test_router(self):
        node = DummyGeneratorNode(self.team, self.user)
        state = node.router(AssistantState(messages=[], intermediate_steps=None))
        assert state == "next"
        state = node.router(
            AssistantState(messages=[], intermediate_steps=[(AgentAction(tool="", tool_input="", log=""), None)])
        )
        assert state == "tools"

    async def test_agent_handles_incomplete_json(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(
            DummyGeneratorNode,
            "_model",
            return_value=RunnableLambda(
                lambda _: (
                    """\n\n{\"query\":{\"kind\":\"RetentionQuery\",\"dateRange\":{\"date_from\":\"2024-01-01\",\"date_to\":\"2024-12-31\"},\"retentionFilter\":{\"period\":\"Week\",\"totalIntervals\":11,\"targetEntity\":{\"name\":\"Application Opened\",\"type\":\"events\"},\"returningEntity\":{\"name\":\"Application Opened\",\"type\":\"events\"}},\"filterTestAccounts\":false}\t \t\t \t\t \t \t"""
                )
            ),
        ):
            new_state = await node(AssistantState(messages=[HumanMessage(content="Text")]), {})
            assert new_state is not None
            assert len(new_state.intermediate_steps or []) == 1


class TestSchemaGeneratorToolsNode(BaseTest):
    async def test_tools_node(self):
        node = SchemaGeneratorToolsNode(self.team, self.user)
        action = AgentAction(tool="fix", tool_input="validationerror", log="pydanticexception")
        state = await node(AssistantState(messages=[], intermediate_steps=[(action, None)]), {})
        state = cast(PartialAssistantState, state)
        result = cast(list[IntermediateStep], state.intermediate_steps)[0][1]
        assert result is not None
        assert "validationerror" in cast(Iterable[Any], result)
        assert "pydanticexception" in cast(Iterable[Any], result)
