from uuid import uuid4

from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessage,
    AssistantTrendsQuery,
    HumanMessage,
    LifecycleQuery,
    NotebookArtifactContent,
    TrendsQuery,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from posthog.models import Insight

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.types import StoredNotebookArtifactContent
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
            await manager.acreate(content, "Test Artifact")

        self.assertIn("Config is required", str(ctx.exception))

    async def test_creates_artifact_persists_to_database(self):
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        manager = ArtifactManager(team=self.team, user=self.user, config=config)
        content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Chart Name",
            description="Chart description",
        )

        artifact = await manager.acreate(content, "Test Artifact")

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

        artifact = await manager.acreate(content, long_name)

        self.assertEqual(len(artifact.name), 400)

    def test_creates_notebook_artifact_with_correct_type(self):
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        manager = ArtifactManager(team=self.team, user=self.user, config=config)
        content = StoredNotebookArtifactContent(blocks=[])

        artifact = async_to_sync(manager.acreate)(content, "Test Notebook")

        self.assertIsNotNone(artifact.id)
        self.assertEqual(artifact.name, "Test Notebook")
        self.assertEqual(artifact.type, AgentArtifact.Type.NOTEBOOK)
        self.assertEqual(artifact.data["blocks"], [])


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

        content = await self.manager.aget(artifact.short_id, VisualizationArtifactContent)

        self.assertEqual(content.name, "Test")

    async def test_raises_when_artifact_not_found(self):
        with self.assertRaises(AgentArtifact.DoesNotExist):
            await self.manager.aget("xxxx")

    def test_retrieves_notebook_content_by_short_id(self):
        artifact = AgentArtifact.objects.create(
            name="Test Notebook",
            type=AgentArtifact.Type.NOTEBOOK,
            data={"blocks": [{"type": "markdown", "content": "Hello"}]},
            conversation=self.conversation,
            team=self.team,
        )

        content = async_to_sync(self.manager.aget)(artifact.short_id, NotebookArtifactContent)

        self.assertIsInstance(content, NotebookArtifactContent)
        self.assertEqual(len(content.blocks), 1)

    def test_retrieves_content_with_expected_type(self):
        artifact = AgentArtifact.objects.create(
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Test"},
            conversation=self.conversation,
            team=self.team,
        )

        content = async_to_sync(self.manager.aget)(artifact.short_id, VisualizationArtifactContent)

        self.assertIsInstance(content, VisualizationArtifactContent)
        self.assertEqual(content.name, "Test")

    def test_raises_type_error_when_expected_type_mismatches(self):
        artifact = AgentArtifact.objects.create(
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Test"},
            conversation=self.conversation,
            team=self.team,
        )

        with self.assertRaises(TypeError) as ctx:
            async_to_sync(self.manager.aget)(artifact.short_id, NotebookArtifactContent)

        self.assertIn("Expected content type=NotebookArtifactContent", str(ctx.exception))
        self.assertIn("got content type=VisualizationArtifactContent", str(ctx.exception))


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

        enriched = await self.manager.aenrich_message(message)

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

        enriched = await self.manager.aenrich_message(artifact_message, state_messages=[viz_message, artifact_message])

        self.assertIsNotNone(enriched)
        assert enriched is not None
        assert isinstance(enriched.content, VisualizationArtifactContent)
        self.assertEqual(enriched.content.name, "Insight")
        self.assertEqual(enriched.content.plan, "test plan")

    async def test_state_source_without_state_messages_raises(self):
        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="ref",
            source=ArtifactSource.STATE,
        )

        with self.assertRaises(ValueError) as ctx:
            await self.manager.aenrich_message(message, state_messages=None)

        self.assertIn("state_messages required", str(ctx.exception))

    async def test_returns_none_when_content_not_found(self):
        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="nonexistent",
            source=ArtifactSource.ARTIFACT,
        )

        enriched = await self.manager.aenrich_message(message)

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

        contents = await self.manager._aget_contents_by_id(messages, aggregate_by="message_id")

        self.assertEqual(len(contents), 2)
        content1 = contents[msg1_id]
        content2 = contents[msg2_id]
        assert isinstance(content1, VisualizationArtifactContent)
        assert isinstance(content2, VisualizationArtifactContent)
        self.assertEqual(content1.name, "First")
        self.assertEqual(content2.name, "Second")

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
        messages: list[VisualizationMessage | ArtifactRefMessage] = [
            viz_message,
            artifact_message,
        ]

        contents = await self.manager._aget_contents_by_id(messages, aggregate_by="message_id")

        self.assertEqual(len(contents), 1)
        content = contents[artifact_msg_id]
        assert isinstance(content, VisualizationArtifactContent)
        self.assertEqual(content.name, "Insight")
        self.assertEqual(content.plan, "state plan")


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
        messages: list[VisualizationMessage | AssistantMessage] = [
            viz_message,
            assistant_msg,
        ]

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
        messages: list[ArtifactRefMessage | AssistantMessage] = [
            artifact_message,
            assistant_msg,
        ]

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

    async def test_fetches_paths_query_insight(self):
        from ee.hogai.artifacts.handlers import VisualizationHandler

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

        viz_handler = VisualizationHandler()
        results = await viz_handler._from_insights_with_models([insight.short_id], self.team)

        self.assertEqual(len(results), 1)
        content, _ = results[insight.short_id]
        self.assertEqual(content.name, "Paths Insight")

    async def test_skips_insight_with_invalid_query(self):
        from ee.hogai.artifacts.handlers import VisualizationHandler

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

        viz_handler = VisualizationHandler()
        results = await viz_handler._from_insights_with_models([insight.short_id], self.team)

        self.assertEqual(len(results), 0)


class TestArtifactManagerGetConversationArtifacts(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        self.manager = ArtifactManager(team=self.team, user=self.user, config=config)

    async def test_returns_all_artifacts_when_no_limit(self):
        for i in range(5):
            await AgentArtifact.objects.acreate(
                name=f"Artifact {i}",
                type=AgentArtifact.Type.VISUALIZATION,
                data={
                    "query": {"kind": "TrendsQuery", "series": []},
                    "name": f"Chart {i}",
                },
                conversation=self.conversation,
                team=self.team,
            )

        artifacts, total_count = await self.manager.aget_conversation_artifacts()

        self.assertEqual(len(artifacts), 5)
        self.assertEqual(total_count, 5)

    async def test_respects_limit(self):
        for i in range(5):
            await AgentArtifact.objects.acreate(
                name=f"Artifact {i}",
                type=AgentArtifact.Type.VISUALIZATION,
                data={
                    "query": {"kind": "TrendsQuery", "series": []},
                    "name": f"Chart {i}",
                },
                conversation=self.conversation,
                team=self.team,
            )

        artifacts, total_count = await self.manager.aget_conversation_artifacts(limit=2)

        self.assertEqual(len(artifacts), 2)
        self.assertEqual(total_count, 5)

    async def test_respects_offset(self):
        for i in range(5):
            await AgentArtifact.objects.acreate(
                name=f"Artifact {i}",
                type=AgentArtifact.Type.VISUALIZATION,
                data={
                    "query": {"kind": "TrendsQuery", "series": []},
                    "name": f"Chart {i}",
                },
                conversation=self.conversation,
                team=self.team,
            )

        artifacts, total_count = await self.manager.aget_conversation_artifacts(limit=2, offset=3)

        self.assertEqual(len(artifacts), 2)
        self.assertEqual(total_count, 5)

    async def test_offset_without_limit_returns_remaining(self):
        for i in range(5):
            await AgentArtifact.objects.acreate(
                name=f"Artifact {i}",
                type=AgentArtifact.Type.VISUALIZATION,
                data={
                    "query": {"kind": "TrendsQuery", "series": []},
                    "name": f"Chart {i}",
                },
                conversation=self.conversation,
                team=self.team,
            )

        artifacts, total_count = await self.manager.aget_conversation_artifacts(offset=3)

        self.assertEqual(len(artifacts), 2)
        self.assertEqual(total_count, 5)

    async def test_returns_empty_for_no_artifacts(self):
        artifacts, total_count = await self.manager.aget_conversation_artifacts()

        self.assertEqual(len(artifacts), 0)
        self.assertEqual(total_count, 0)

    async def test_only_returns_artifacts_from_same_conversation(self):
        other_conversation = await Conversation.objects.acreate(user=self.user, team=self.team)
        await AgentArtifact.objects.acreate(
            name="Same Conversation",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Same"},
            conversation=self.conversation,
            team=self.team,
        )
        await AgentArtifact.objects.acreate(
            name="Other Conversation",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Other"},
            conversation=other_conversation,
            team=self.team,
        )

        artifacts, total_count = await self.manager.aget_conversation_artifacts()

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(total_count, 1)
        assert isinstance(artifacts[0].content, VisualizationArtifactContent)
        self.assertEqual(artifacts[0].content.name, "Same")


class TestArtifactManagerGetVisualizationWithSource(BaseTest):
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

        result = await self.manager.aget_visualization([], insight.short_id)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source, ArtifactSource.INSIGHT)
        assert isinstance(result.content, VisualizationArtifactContent)
        self.assertEqual(result.content.name, "Lifecycle Insight")
        self.assertEqual(result.content.description, "Test lifecycle insight")
        assert isinstance(result.content.query, LifecycleQuery)

    async def test_retrieves_visualizations_in_batch(self):
        """Test that aget_visualizations returns ordered list matching input IDs."""
        insight1 = await Insight.objects.acreate(
            team=self.team,
            name="First Insight",
            saved=True,
            query={"source": {"kind": "TrendsQuery", "series": []}},
        )
        insight2 = await Insight.objects.acreate(
            team=self.team,
            name="Second Insight",
            saved=True,
            query={"source": {"kind": "TrendsQuery", "series": []}},
        )

        # Request in specific order
        results = await self.manager.aget_visualizations([], [insight2.short_id, insight1.short_id, "nonexistent"])

        self.assertEqual(len(results), 3)
        # Results should match input order
        assert results[0] is not None
        assert results[1] is not None
        assert results[2] is None  # nonexistent
        assert isinstance(results[0].content, VisualizationArtifactContent)
        assert isinstance(results[1].content, VisualizationArtifactContent)
        self.assertEqual(results[0].content.name, "Second Insight")
        self.assertEqual(results[1].content.name, "First Insight")


class TestArtifactManagerUpdate(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.manager = ArtifactManager(team=self.team, user=self.user)

    async def test_updates_existing_artifact_data(self):
        artifact = await AgentArtifact.objects.acreate(
            name="Original Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Original"},
            conversation=self.conversation,
            team=self.team,
        )
        new_content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Updated Name",
            description="Updated description",
        )

        updated = await self.manager.aupdate(artifact.short_id, new_content)

        self.assertEqual(updated.short_id, artifact.short_id)
        self.assertEqual(updated.data["name"], "Updated Name")
        self.assertEqual(updated.data["description"], "Updated description")

    async def test_raises_when_artifact_not_found(self):
        new_content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Test",
        )

        with self.assertRaises(ValueError) as ctx:
            await self.manager.aupdate("nonexistent", new_content)

        self.assertIn("not found", str(ctx.exception))


class TestArtifactManagerGetContentsByArtifactId(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.manager = ArtifactManager(team=self.team, user=self.user)

    async def test_aggregate_by_artifact_id_groups_correctly(self):
        artifact = await AgentArtifact.objects.acreate(
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Test"},
            conversation=self.conversation,
            team=self.team,
        )
        messages = [
            ArtifactRefMessage(
                id=str(uuid4()),
                content_type=ArtifactContentType.VISUALIZATION,
                artifact_id=artifact.short_id,
                source=ArtifactSource.ARTIFACT,
            ),
        ]

        contents = await self.manager._aget_contents_by_id(messages, aggregate_by="artifact_id")

        self.assertEqual(len(contents), 1)
        self.assertIn(artifact.short_id, contents)
        content = contents[artifact.short_id]
        assert isinstance(content, VisualizationArtifactContent)
        self.assertEqual(content.name, "Test")

    async def test_filter_by_artifact_ids_filters_results(self):
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
        messages = [
            ArtifactRefMessage(
                id=str(uuid4()),
                content_type=ArtifactContentType.VISUALIZATION,
                artifact_id=artifact1.short_id,
                source=ArtifactSource.ARTIFACT,
            ),
            ArtifactRefMessage(
                id=str(uuid4()),
                content_type=ArtifactContentType.VISUALIZATION,
                artifact_id=artifact2.short_id,
                source=ArtifactSource.ARTIFACT,
            ),
        ]

        contents = await self.manager._aget_contents_by_id(
            messages,
            aggregate_by="artifact_id",
            filter_by_artifact_ids=[artifact1.short_id],
        )

        self.assertEqual(len(contents), 1)
        self.assertIn(artifact1.short_id, contents)
        self.assertNotIn(artifact2.short_id, contents)


class TestArtifactTypeRegistry(BaseTest):
    def setUp(self):
        super().setUp()
        self.manager = ArtifactManager(team=self.team, user=self.user)

    def test_get_db_type_for_visualization_content(self):
        content = VisualizationArtifactContent(query=AssistantTrendsQuery(series=[]))

        db_type = self.manager._get_db_type_for_content(content)

        self.assertEqual(db_type, AgentArtifact.Type.VISUALIZATION)

    def test_get_db_type_for_notebook_content(self):
        content = StoredNotebookArtifactContent(blocks=[])

        db_type = self.manager._get_db_type_for_content(content)

        self.assertEqual(db_type, AgentArtifact.Type.NOTEBOOK)
