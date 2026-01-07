import json
from collections.abc import Iterable
from typing import Any, cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from langchain_core.agents import AgentAction
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantMessage,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    VisualizationArtifactContent,
)

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
from ee.models import AgentArtifact, Conversation
import pytest

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

    async def test_agent_reconstructs_conversation_and_does_not_add_an_empty_plan(self):
        node = DummyGeneratorNode(self.team, self.user)
        history = await node._construct_messages(
            AssistantState(messages=[HumanMessage(content="Text", id="0")], start_id="0")
        )
        assert len(history) == 2
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "Answer to this question:" in history[1].content
        assert "{{question}}" not in history[1].content

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
        assert len(history) == 3
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "the plan" in history[1].content
        assert "{{plan}}" not in history[1].content
        assert "randomplan" in history[1].content
        assert history[2].type == "human"
        assert "Answer to this question:" in history[2].content
        assert "{{question}}" not in history[2].content
        assert "Text" in history[2].content

    async def test_agent_reconstructs_conversation_can_handle_follow_ups(self):
        node = DummyGeneratorNode(self.team, self.user)
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=self.basic_trends, name="Query", description="Description 1", plan="randomplan"
            ).model_dump(),
        )
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Multiple questions", id="0"),
                    ArtifactRefMessage(
                        content_type=ArtifactContentType.VISUALIZATION,
                        source=ArtifactSource.ARTIFACT,
                        artifact_id=str(artifact.short_id),
                        id="1",
                    ),
                    HumanMessage(content="Follow Up", id="2"),
                ],
                plan="newrandomplan",
                start_id="2",
            )
        )

        assert len(history) == 6
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "the plan" in history[1].content
        assert "{{plan}}" not in history[1].content
        assert "randomplan" in history[1].content
        assert history[2].type == "human"
        assert "Answer to this question:" in history[2].content
        assert "{{question}}" not in history[2].content
        assert "Query" in history[2].content
        assert history[3].type == "ai"
        assert history[3].content == self.basic_trends.model_dump_json()
        assert history[4].type == "human"
        assert "the new plan" in history[4].content
        assert "{{plan}}" not in history[4].content
        assert "newrandomplan" in history[4].content
        assert history[5].type == "human"
        assert "Answer to this question:" in history[5].content
        assert "{{question}}" not in history[5].content
        assert "Follow Up" in history[5].content

    async def test_agent_reconstructs_typical_conversation(self):
        node = DummyGeneratorNode(self.team, self.user)
        artifact1 = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact 1",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=self.basic_trends, name="Query 1", description="Description 1", plan="Plan 1"
            ).model_dump(),
        )
        artifact2 = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact 2",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=self.basic_trends, name="Query 2", description="Description 2", plan="Plan 2"
            ).model_dump(),
        )
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Question 1", id="0"),
                    ArtifactRefMessage(
                        content_type=ArtifactContentType.VISUALIZATION,
                        source=ArtifactSource.ARTIFACT,
                        artifact_id=str(artifact1.short_id),
                        id="1",
                    ),
                    AssistantMessage(content="Summary 1", id="3"),
                    HumanMessage(content="Question 2", id="4"),
                    ArtifactRefMessage(
                        content_type=ArtifactContentType.VISUALIZATION,
                        source=ArtifactSource.ARTIFACT,
                        artifact_id=str(artifact2.short_id),
                        id="5",
                    ),
                    AssistantMessage(content="Summary 2", id="7"),
                    HumanMessage(content="Question 3", id="8"),
                ],
                plan="Plan 3",
                start_id="8",
                root_tool_insight_plan="Query 3",
            )
        )

        assert len(history) == 9
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "Plan 1" in history[1].content
        assert history[2].type == "human"
        assert "Query 1" in history[2].content
        assert history[3].type == "ai"
        AssistantTrendsQuery.model_validate_json(cast(str, history[3].content))
        assert history[4].type == "human"
        assert "Plan 2" in history[4].content
        assert history[5].type == "human"
        assert "Query 2" in history[5].content
        assert history[6].type == "ai"
        AssistantTrendsQuery.model_validate_json(cast(str, history[6].content))
        assert history[7].type == "human"
        assert "Plan 3" in history[7].content
        assert history[8].type == "human"
        assert "Query 3" in history[8].content

    async def test_prompt_messages_merged(self):
        node = DummyGeneratorNode(self.team, self.user)
        artifact1 = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact 1",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=self.basic_trends, name="Test Artifact 1", description="Test Description 1", plan="Plan 1"
            ).model_dump(),
        )
        artifact2 = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact 2",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=self.basic_trends, name="Test Artifact 2", description="Test Description 2", plan="Plan 2"
            ).model_dump(),
        )
        state = AssistantState(
            messages=[
                HumanMessage(content="Question 1", id="0"),
                ArtifactRefMessage(
                    content_type=ArtifactContentType.VISUALIZATION,
                    source=ArtifactSource.ARTIFACT,
                    artifact_id=str(artifact1.short_id),
                    id="1",
                ),
                AssistantMessage(content="Summary 1", id="3"),
                HumanMessage(content="Question 2", id="4"),
                ArtifactRefMessage(
                    content_type=ArtifactContentType.VISUALIZATION,
                    source=ArtifactSource.ARTIFACT,
                    artifact_id=str(artifact2.short_id),
                    id="5",
                ),
                AssistantMessage(content="Summary 2", id="7"),
                HumanMessage(content="Question 3", id="8"),
            ],
            plan="Plan 3",
            start_id="8",
        )
        with patch.object(DummyGeneratorNode, "_model") as generator_model_mock:

            def assert_prompt(prompt):
                assert len(prompt) == 6
                assert prompt[0].type == "system"
                assert prompt[1].type == "human"
                assert prompt[2].type == "ai"
                assert prompt[3].type == "human"
                assert prompt[4].type == "ai"
                assert prompt[5].type == "human"

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
            with pytest.raises(SchemaGenerationException) as cm:
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
            assert cm.value.llm_output == '{"query": "test"}'
            assert cm.value.validation_message == "Quality check failed"

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

            with pytest.raises(SchemaGenerationException):
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
        assert len(history) == 4
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "the plan" in history[1].content
        assert "{{plan}}" not in history[1].content
        assert "randomplan" in history[1].content
        assert history[2].type == "human"
        assert "Answer to this question:" in history[2].content
        assert "{{question}}" not in history[2].content
        assert "Text" in history[2].content
        assert history[3].type == "human"
        assert "Pydantic" in history[3].content
        assert "uniqexception" in history[3].content

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
        assert len(history) == 3
        assert history[0].type == "human"
        assert "mapping" in history[0].content
        assert history[1].type == "human"
        assert "the plan" in history[1].content
        assert "{{plan}}" not in history[1].content
        assert "randomplan" in history[1].content
        assert history[2].type == "human"
        assert "Answer to this question:" in history[2].content
        assert "{{question}}" not in history[2].content
        assert "Text" in history[2].content

    def test_router(self):
        node = DummyGeneratorNode(self.team, self.user)
        state = node.router(AssistantState(messages=[], intermediate_steps=None))
        assert state == "next"
        state = node.router(
            AssistantState(messages=[], intermediate_steps=[(AgentAction(tool="", tool_input="", log=""), None)])
        )
        assert state == "tools"

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
        assert len(history) == 2
        assert history[0].type == "human"
        assert "group" in history[0].content
        assert history[1].type == "human"
        assert "Foobar" in history[1].content
        assert "{{question}}" not in history[1].content

    async def test_injects_insight_description_and_keeps_original_question(self):
        node = DummyGeneratorNode(self.team, self.user)
        artifact = await AgentArtifact.objects.acreate(
            team=self.team,
            conversation=self.conversation,
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=self.basic_trends, name="Query 1", description="Description 1", plan="Plan 1"
            ).model_dump(),
        )
        history = await node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Original question", id="1"),
                    ArtifactRefMessage(
                        content_type=ArtifactContentType.VISUALIZATION,
                        source=ArtifactSource.ARTIFACT,
                        artifact_id=str(artifact.short_id),
                        id="2",
                    ),
                    HumanMessage(content="Second question", id="3"),
                ],
                start_id="3",
                root_tool_insight_plan="Foobar",
                root_tool_insight_type="trends",
            )
        )
        assert len(history) == 5
        assert history[0].type == "human"
        assert "group" in history[0].content
        assert history[1].type == "human"
        assert "Plan 1" in history[1].content
        assert "{{question}}" not in history[1].content
        assert history[2].type == "human"
        assert "Query 1" in history[2].content
        assert "{{question}}" not in history[2].content
        assert history[3].type == "ai"
        assert history[4].type == "human"
        assert "Foobar" in history[4].content
        assert "{{question}}" not in history[4].content

    async def test_keeps_maximum_number_of_viz_messages(self):
        node = DummyGeneratorNode(self.team, self.user)
        query = AssistantTrendsQuery(series=[])
        messages = []
        for i in range(7):
            artifact = await AgentArtifact.objects.acreate(
                team=self.team,
                conversation=self.conversation,
                name=f"Test Artifact {i + 1}",
                type=AgentArtifact.Type.VISUALIZATION,
                data=VisualizationArtifactContent(
                    query=query, name=f"Query {i + 1}", description=f"Description {i + 1}", plan=f"Plan {i + 1}"
                ).model_dump(),
            )
            messages.append(
                ArtifactRefMessage(
                    content_type=ArtifactContentType.VISUALIZATION,
                    source=ArtifactSource.ARTIFACT,
                    artifact_id=str(artifact.short_id),
                    id=str(uuid4()),
                )
            )
        history = await node._construct_messages(
            AssistantState(
                messages=messages,
                root_tool_insight_plan="Query 8",
                root_tool_insight_type="trends",
            )
        )
        assert len(history) == 17
        assert history[0].type == "human"
        assert "group" in history[0].content

        # Query 3
        assert history[1].type == "human"
        assert "Plan 3" in history[1].content
        assert history[2].type == "human"
        assert "Query 3" in history[2].content
        assert history[3].type == "ai"

        # Query 4
        assert history[4].type == "human"
        assert "Plan 4" in history[4].content
        assert history[5].type == "human"
        assert "Query 4" in history[5].content
        assert history[6].type == "ai"

        # Query 5
        assert history[7].type == "human"
        assert "Plan 5" in history[7].content
        assert history[8].type == "human"
        assert "Query 5" in history[8].content
        assert history[9].type == "ai"

        # Query 6
        assert history[10].type == "human"
        assert "Plan 6" in history[10].content
        assert history[11].type == "human"
        assert "Query 6" in history[11].content
        assert history[12].type == "ai"

        # Query 7
        assert history[13].type == "human"
        assert "Plan 7" in history[13].content
        assert history[14].type == "human"
        assert "Query 7" in history[14].content
        assert history[15].type == "ai"

        # New query
        assert history[16].type == "human"
        assert "Query 8" in history[16].content

    async def test_agent_handles_incomplete_json(self):
        node = DummyGeneratorNode(self.team, self.user)
        with patch.object(
            DummyGeneratorNode,
            "_model",
            return_value=RunnableLambda(
                lambda _: """\n\n{\"query\":{\"kind\":\"RetentionQuery\",\"dateRange\":{\"date_from\":\"2024-01-01\",\"date_to\":\"2024-12-31\"},\"retentionFilter\":{\"period\":\"Week\",\"totalIntervals\":11,\"targetEntity\":{\"name\":\"Application Opened\",\"type\":\"events\"},\"returningEntity\":{\"name\":\"Application Opened\",\"type\":\"events\"}},\"filterTestAccounts\":false}\t \t\t \t\t \t \t"""
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
        assert "validationerror" is not None, cast(list[IntermediateStep], state.intermediate_steps)[0][1]
        assert "validationerror" in cast(Iterable[Any], cast(list[IntermediateStep], state.intermediate_steps)[0][1])
        assert "pydanticexception" in cast(Iterable[Any], cast(list[IntermediateStep], state.intermediate_steps)[0][1])
