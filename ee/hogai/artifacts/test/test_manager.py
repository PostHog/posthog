from uuid import uuid4

from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessage,
    AssistantTrendsQuery,
    HumanMessage,
    LifecycleQuery,
    TrendsQuery,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from posthog.models import Insight

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.utils.types.base import ArtifactRefMessage
from ee.models.assistant import AgentArtifact, Conversation


class TestArtifactManagerCreateMessage(BaseTest):
    def setUp(self):
        super().setUp()
        self.manager = ArtifactManager(team=self.team, user=self.user)

    def test_creates_artifact_message_with_defaults(self):
        artifact_id = "abc123"
        message = self.manager.create_message(artifact_id)

        self.assertEqual(message.artifact_id, artifact_id)
        self.assertEqual(message.source, ArtifactSource.ARTIFACT)
        self.assertEqual(message.content_type, ArtifactContentType.VISUALIZATION)
        self.assertIsNotNone(message.id)


class TestArtifactManagerCreate(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    async def test_creates_artifact_without_config_raises(self):
        manager = ArtifactManager(team=self.team, user=self.user, config=None)
        content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Test",
        )

        with self.assertRaises(ValueError) as ctx:
            await manager.create(content, "Test Artifact")

        self.assertIn("Config is required", str(ctx.exception))

    async def test_creates_artifact_persists_to_database(self):
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        manager = ArtifactManager(team=self.team, user=self.user, config=config)
        content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Chart Name",
            description="Chart description",
        )

        artifact = await manager.create(content, "Test Artifact")

        self.assertIsNotNone(artifact.id)
        self.assertEqual(artifact.name, "Test Artifact")
        self.assertEqual(artifact.type, AgentArtifact.Type.VISUALIZATION)
        self.assertEqual(artifact.team_id, self.team.id)
        self.assertEqual(artifact.conversation_id, self.conversation.id)
        self.assertEqual(artifact.data["name"], "Chart Name")

    async def test_creates_artifact_truncates_long_name(self):
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        manager = ArtifactManager(team=self.team, user=self.user, config=config)
        content = VisualizationArtifactContent(query=AssistantTrendsQuery(series=[]))
        long_name = "A" * 500

        artifact = await manager.create(content, long_name)

        self.assertEqual(len(artifact.name), 400)


class TestArtifactManagerGetContentByShortId(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.manager = ArtifactManager(team=self.team, user=self.user)

    async def test_retrieves_content_by_short_id(self):
        artifact = await AgentArtifact.objects.acreate(
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Test"},
            conversation=self.conversation,
            team=self.team,
        )

        content = await self.manager.aget_content_by_short_id(artifact.short_id)

        self.assertEqual(content.name, "Test")

    async def test_raises_when_artifact_not_found(self):
        with self.assertRaises(AgentArtifact.DoesNotExist):
            await self.manager.aget_content_by_short_id("xxxx")


class TestArtifactManagerGetEnrichedMessage(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.manager = ArtifactManager(team=self.team, user=self.user)

    async def test_enriches_artifact_source_message(self):
        artifact = await AgentArtifact.objects.acreate(
            name="Enriched Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Enriched"},
            conversation=self.conversation,
            team=self.team,
        )
        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )

        enriched = await self.manager.aget_enriched_message(message)

        self.assertIsNotNone(enriched)
        assert enriched is not None
        assert isinstance(enriched.content, VisualizationArtifactContent)
        self.assertEqual(enriched.content.name, "Enriched")

    async def test_enriches_state_source_message(self):
        viz_msg_id = str(uuid4())
        viz_message = VisualizationMessage(
            id=viz_msg_id,
            query="test query",
            answer=TrendsQuery(series=[]),
            plan="test plan",
        )
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=viz_msg_id,
            source=ArtifactSource.STATE,
        )

        enriched = await self.manager.aget_enriched_message(
            artifact_message, state_messages=[viz_message, artifact_message]
        )

        self.assertIsNotNone(enriched)
        assert enriched is not None
        assert isinstance(enriched.content, VisualizationArtifactContent)
        self.assertEqual(enriched.content.name, "test query")
        self.assertEqual(enriched.content.plan, "test plan")

    async def test_state_source_without_state_messages_raises(self):
        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="ref",
            source=ArtifactSource.STATE,
        )

        with self.assertRaises(ValueError) as ctx:
            await self.manager.aget_enriched_message(message, state_messages=None)

        self.assertIn("state_messages required", str(ctx.exception))

    async def test_returns_none_when_content_not_found(self):
        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="nonexistent",
            source=ArtifactSource.ARTIFACT,
        )

        enriched = await self.manager.aget_enriched_message(message)

        self.assertIsNone(enriched)


class TestArtifactManagerGetContentsByMessageId(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.manager = ArtifactManager(team=self.team, user=self.user)

    async def test_fetches_artifact_contents_in_batch(self):
        artifact1 = await AgentArtifact.objects.acreate(
            name="Artifact 1",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "First"},
            conversation=self.conversation,
            team=self.team,
        )
        artifact2 = await AgentArtifact.objects.acreate(
            name="Artifact 2",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Second"},
            conversation=self.conversation,
            team=self.team,
        )
        msg1_id = str(uuid4())
        msg2_id = str(uuid4())
        messages = [
            ArtifactRefMessage(
                id=msg1_id,
                content_type=ArtifactContentType.VISUALIZATION,
                artifact_id=artifact1.short_id,
                source=ArtifactSource.ARTIFACT,
            ),
            ArtifactRefMessage(
                id=msg2_id,
                content_type=ArtifactContentType.VISUALIZATION,
                artifact_id=artifact2.short_id,
                source=ArtifactSource.ARTIFACT,
            ),
        ]

        contents = await self.manager.aget_contents_by_message_id(messages)

        self.assertEqual(len(contents), 2)
        self.assertEqual(contents[msg1_id].name, "First")
        self.assertEqual(contents[msg2_id].name, "Second")

    async def test_extracts_content_from_state_visualization_messages(self):
        viz_id = str(uuid4())
        viz_message = VisualizationMessage(
            id=viz_id,
            query="state query",
            answer=TrendsQuery(series=[]),
            plan="state plan",
        )
        artifact_msg_id = str(uuid4())
        artifact_message = ArtifactRefMessage(
            id=artifact_msg_id,
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=viz_id,
            source=ArtifactSource.STATE,
        )
        messages: list[VisualizationMessage | ArtifactRefMessage] = [viz_message, artifact_message]

        contents = await self.manager.aget_contents_by_message_id(messages)

        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[artifact_msg_id].name, "state query")
        self.assertEqual(contents[artifact_msg_id].plan, "state plan")


class TestArtifactManagerEnrichMessages(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.manager = ArtifactManager(team=self.team, user=self.user)

    async def test_converts_artifact_messages_to_visualization_artifact_messages(self):
        artifact = await AgentArtifact.objects.acreate(
            name="Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Enriched"},
            conversation=self.conversation,
            team=self.team,
        )
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )
        messages = [artifact_message]

        enriched = await self.manager.aenrich_messages(messages)

        self.assertEqual(len(enriched), 1)
        msg = enriched[0]
        assert isinstance(msg, ArtifactMessage)
        assert isinstance(msg.content, VisualizationArtifactContent)
        self.assertEqual(msg.content.name, "Enriched")

    async def test_passes_through_non_artifact_messages(self):
        assistant_msg = AssistantMessage(id=str(uuid4()), content="Hello")
        human_msg = HumanMessage(id=str(uuid4()), content="Hi")
        messages: list[AssistantMessage | HumanMessage] = [assistant_msg, human_msg]

        enriched = await self.manager.aenrich_messages(messages)

        self.assertEqual(len(enriched), 2)
        self.assertEqual(enriched[0], assistant_msg)
        self.assertEqual(enriched[1], human_msg)

    async def test_filters_visualization_messages(self):
        viz_message = VisualizationMessage(
            id=str(uuid4()),
            query="query",
            answer=TrendsQuery(series=[]),
            plan="plan",
        )
        assistant_msg = AssistantMessage(id=str(uuid4()), content="Hello")
        messages: list[VisualizationMessage | AssistantMessage] = [viz_message, assistant_msg]

        enriched = await self.manager.aenrich_messages(messages)

        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0], assistant_msg)

    async def test_artifacts_only_flag_filters_non_artifact_messages(self):
        artifact = await AgentArtifact.objects.acreate(
            name="Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Only"},
            conversation=self.conversation,
            team=self.team,
        )
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )
        assistant_msg = AssistantMessage(id=str(uuid4()), content="Hello")
        messages: list[ArtifactRefMessage | AssistantMessage] = [artifact_message, assistant_msg]

        enriched = await self.manager.aenrich_messages(messages, artifacts_only=True)

        self.assertEqual(len(enriched), 1)
        msg = enriched[0]
        assert isinstance(msg, ArtifactMessage)
        assert isinstance(msg.content, VisualizationArtifactContent)
        self.assertEqual(msg.content.name, "Only")

    async def test_skips_artifact_messages_without_content(self):
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="nonexistent",
            source=ArtifactSource.ARTIFACT,
        )
        messages = [artifact_message]

        enriched = await self.manager.aenrich_messages(messages)

        self.assertEqual(len(enriched), 0)

    async def test_fetches_trends_query_insight(self):
        insight = await Insight.objects.acreate(
            team=self.team,
            name="Trends Insight",
            saved=True,
            query={
                "source": {
                    "kind": "TrendsQuery",
                    "series": [],
                }
            },
        )

        contents = await self.manager._afetch_insight_contents([insight.short_id])

        self.assertEqual(len(contents), 1)
        content = contents[insight.short_id]
        self.assertEqual(content.name, "Trends Insight")

    async def test_fetches_paths_query_insight(self):
        insight = await Insight.objects.acreate(
            team=self.team,
            name="Paths Insight",
            description="Test paths insight",
            saved=True,
            query={
                "source": {
                    "kind": "PathsQuery",
                    "pathsFilter": {"includeEventTypes": ["$pageview"]},
                }
            },
        )

        contents = await self.manager._afetch_insight_contents([insight.short_id])

        self.assertEqual(len(contents), 1)
        content = contents[insight.short_id]
        self.assertEqual(content.name, "Paths Insight")

    async def test_skips_insight_with_invalid_query(self):
        insight = await Insight.objects.acreate(
            team=self.team,
            name="Invalid Insight",
            saved=True,
            query={
                "source": {
                    "kind": "InvalidQueryType",
                    "data": "invalid",
                }
            },
        )

        contents = await self.manager._afetch_insight_contents([insight.short_id])

        self.assertEqual(len(contents), 0)


class TestArtifactManagerGetInsightWithSource(BaseTest):
    def setUp(self):
        super().setUp()
        self.manager = ArtifactManager(team=self.team, user=self.user)

    async def test_retrieves_lifecycle_query_insight(self):
        insight = await Insight.objects.acreate(
            team=self.team,
            name="Lifecycle Insight",
            description="Test lifecycle insight",
            saved=True,
            query={
                "source": {
                    "kind": "LifecycleQuery",
                    "series": [{"kind": "EventsNode", "name": "$pageview"}],
                }
            },
        )

        result = await self.manager.aget_insight_with_source([], insight.short_id)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source, ArtifactSource.INSIGHT)
        self.assertEqual(result.content.name, "Lifecycle Insight")
        self.assertEqual(result.content.description, "Test lifecycle insight")
        assert isinstance(result.content.query, LifecycleQuery)
