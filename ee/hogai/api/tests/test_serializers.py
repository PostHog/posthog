from dataclasses import replace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from posthog.schema import (
    AgentMode,
    ArtifactContentType,
    ArtifactSource,
    AssistantMessage,
    AssistantToolCallMessage,
    ContextMessage,
)

from products.posthog_ai.backend.models.assistant import AgentArtifact, Conversation
from products.tasks.backend.facade.contracts import TaskDetailDTO, TaskRunDetailDTO
from products.tasks.backend.models import Task

from ee.hogai.api.serializers import (
    ConversationMinimalSerializer,
    ConversationSerializer,
    ConversationTaskSerializer,
    TaskSerializer,
)
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage


class TestConversationSerializers(APIBaseTest):
    def test_message_filtering_behavior(self):
        """
        Test that the message filtering in ConversationSerializer works correctly:
        - Context Messages should be excluded
        """
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation for filtering", type=Conversation.Type.ASSISTANT
        )

        # Create mock state with various types of messages
        mock_messages = [
            # Should be included: AssistantMessage with content
            AssistantMessage(content="This message has content", type="ai"),
            # Should be excluded: Empty AssistantMessage
            AssistantMessage(content="", type="ai"),
            # Should be included
            AssistantToolCallMessage(
                content="Tool result", tool_call_id="123", type="tool", ui_payload={"some": "data"}
            ),
            # Should be included
            AssistantToolCallMessage(content="Tool result", tool_call_id="456", type="tool", ui_payload=None),
            # Should be excluded: Context Message
            ContextMessage(content="This is a context message", type="context"),
        ]

        state = AssistantState(messages=mock_messages)

        # Mock the get_state method to return our test data
        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "assistant_graph": AssistantGraph(self.team, self.user).compile_full_graph(),
                    "team": self.team,
                    "user": self.user,
                },
            ).data

            # Check that only the expected messages are included
            filtered_messages = data["messages"]
            self.assertEqual(len(filtered_messages), 3)

            # First message should be the AssistantMessage with content
            self.assertEqual(filtered_messages[0]["content"], "This message has content")

            # Second message should be the AssistantToolCallMessage with UI payload
            self.assertEqual(filtered_messages[1]["ui_payload"], {"some": "data"})

            # Third message should be the AssistantToolCallMessage without UI payload
            self.assertEqual(filtered_messages[2]["ui_payload"], None)

    def test_get_messages_handles_validation_errors_and_sets_unsupported_content(self):
        """Gracefully fall back to an empty list when the stored state fails validation, and set has_unsupported_content."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with invalid state", type=Conversation.Type.ASSISTANT
        )

        # Use an invalid payload to trigger a Pydantic validation error on AssistantState.model_validate
        invalid_snapshot = type("Snapshot", (), {"values": {"messages": [{"not": "a valid message"}]}})()

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:
            mock_get_state.return_value = invalid_snapshot

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(data["messages"], [])
        self.assertTrue(data["has_unsupported_content"])

    def test_has_unsupported_content_on_other_errors(self):
        """On non-validation errors, has_unsupported_content should be False."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with graph error", type=Conversation.Type.ASSISTANT
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:
            mock_get_state.side_effect = RuntimeError("Graph compilation failed")

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(data["messages"], [])
        self.assertFalse(data["has_unsupported_content"])

    def test_has_unsupported_content_on_success(self):
        """On successful message fetch, has_unsupported_content should be False."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Valid conversation", type=Conversation.Type.ASSISTANT
        )

        state = AssistantState(messages=[AssistantMessage(content="Test message", type="ai")])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(len(data["messages"]), 1)
        self.assertFalse(data["has_unsupported_content"])

    def test_agent_mode_defaults_when_missing(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation without agent mode", type=Conversation.Type.ASSISTANT
        )

        state = AssistantState(messages=[AssistantMessage(content="Test message", type="ai")])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(data["agent_mode"], AgentMode.PRODUCT_ANALYTICS.value)

    def test_agent_mode_returns_state_value(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with agent mode", type=Conversation.Type.ASSISTANT
        )

        state = AssistantState(messages=[AssistantMessage(content="Test message", type="ai")], agent_mode=AgentMode.SQL)

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(data["agent_mode"], AgentMode.SQL.value)

    def test_caching_prevents_duplicate_operations(self):
        """This is to test that the caching works correctly as to not incurring in unnecessary operations (We would do a DRF call per field call)."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Cached conversation", type=Conversation.Type.ASSISTANT
        )

        state = AssistantState(messages=[AssistantMessage(content="Cached message", type="ai")])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            serializer = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            )

            # Explicitly access both fields multiple times
            _ = serializer.data["messages"]
            _ = serializer.data["has_unsupported_content"]
            _ = serializer.data["agent_mode"]
            _ = serializer.data["messages"]
            _ = serializer.data["has_unsupported_content"]

        # aget_state should only be called once though
        self.assertEqual(mock_get_state.call_count, 1)


class TestConversationSerializerRuntimeMessages(APIBaseTest):
    def test_sandbox_conversation_returns_empty_messages(self):
        """Sandbox conversations don't persist messages Django-side — `messages` is always empty."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Sandbox conversation",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
            messages_json=[{"type": "ai", "content": "should be ignored on the sandbox path"}],
        )

        # aget_state must never be invoked for a sandbox conversation — the guard short-circuits first.
        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:
            data = ConversationSerializer(
                conversation,
                context={"team": self.team, "user": self.user},
            ).data

        self.assertEqual(data["messages"], [])
        self.assertEqual(data["agent_runtime"], Conversation.AgentRuntime.SANDBOX.value)
        mock_get_state.assert_not_called()

    def test_langgraph_conversation_returns_populated_messages(self):
        """LangGraph conversations keep today's behavior — messages come from the graph state."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="LangGraph conversation",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )

        state = AssistantState(messages=[AssistantMessage(content="Hello from LangGraph", type="ai")])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={"team": self.team, "user": self.user},
            ).data

        self.assertEqual(data["agent_runtime"], Conversation.AgentRuntime.LANGGRAPH.value)
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["content"], "Hello from LangGraph")


class TestConversationSerializerTaskField(APIBaseTest):
    def _serialize(self, conversation: Conversation) -> dict:
        return ConversationSerializer(conversation, context={"team": self.team, "user": self.user}).data

    def _sandbox_conversation(self, task: Task | None = None) -> Conversation:
        return Conversation.objects.create(
            user=self.user,
            team=self.team,
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
            task=task,
        )

    def _task(self) -> Task:
        return Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )

    def _task_dto(self) -> TaskDetailDTO:
        task_id = uuid4()
        run = TaskRunDetailDTO(
            id=uuid4(),
            task=task_id,
            stage=None,
            branch=None,
            status="queued",
            environment="local",
            runtime_adapter=None,
            provider=None,
            model=None,
            reasoning_effort=None,
            log_url=None,
            error_message=None,
            output=None,
            state={},
        )
        return TaskDetailDTO(
            id=task_id,
            task_number=1,
            slug="task-1",
            title="t",
            title_manually_set=False,
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            repository=None,
            github_integration=None,
            github_user_integration=None,
            signal_report=None,
            json_schema=None,
            internal=False,
            archived=False,
            archived_at=None,
            ci_prompt=None,
            latest_run=run,
            latest_run_id=run.id,
        )

    def test_task_serializer_nests_latest_run_detail(self):
        task_dto = self._task_dto()

        data = TaskSerializer(task_dto).data

        assert task_dto.latest_run is not None
        self.assertEqual(data["latest_run"]["id"], str(task_dto.latest_run.id))

    def test_conversation_task_serializer_outputs_latest_run_id(self):
        task_dto = self._task_dto()

        data = ConversationTaskSerializer(task_dto).data

        self.assertEqual(data["latest_run"], str(task_dto.latest_run_id))

    def test_conversation_task_serializer_latest_run_null_without_run(self):
        task_dto = replace(self._task_dto(), latest_run=None, latest_run_id=None)

        data = ConversationTaskSerializer(task_dto).data

        self.assertIsNone(data["latest_run"])

    def test_task_is_null_before_first_message(self):
        # A sandbox conversation gets its Task FK on the first message, not at creation.
        data = self._serialize(self._sandbox_conversation())
        self.assertIsNone(data["task"])
        self.assertTrue(data["is_sandbox"])

    def test_langgraph_conversation_has_null_task_and_is_not_sandbox(self):
        conversation = Conversation.objects.create(user=self.user, team=self.team, type=Conversation.Type.ASSISTANT)

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = AssistantState(messages=[]).model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()
            data = self._serialize(conversation)

        self.assertIsNone(data["task"])
        self.assertFalse(data["is_sandbox"])

    def test_task_latest_run_null_when_task_has_no_runs(self):
        task = self._task()
        data = self._serialize(self._sandbox_conversation(task))
        self.assertEqual(data["task"]["id"], str(task.id))
        # The conversation envelope carries the latest run id (null here), not nested run details.
        self.assertIsNone(data["task"]["latest_run"])
        self.assertEqual(data["task"]["title"], "t")

    def test_task_latest_run_is_latest_run_id_when_task_has_runs(self):
        task = self._task()
        task.create_run(mode="interactive")
        task.create_run(mode="interactive")

        data = self._serialize(self._sandbox_conversation(task))

        self.assertEqual(data["task"]["id"], str(task.id))
        latest_run = task.latest_run
        assert latest_run is not None
        self.assertEqual(data["task"]["latest_run"], str(latest_run.id))


class TestTaskLatestRun(APIBaseTest):
    def _task_with_runs(self, count: int) -> tuple[Task, list]:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        runs = [task.create_run(mode="interactive") for _ in range(count)]
        return task, runs

    def test_non_prefetched_fast_path_single_query(self):
        task, runs = self._task_with_runs(5)
        fresh = Task.objects.get(pk=task.pk)

        with self.assertNumQueries(1):
            latest = fresh.latest_run

        assert latest is not None
        self.assertEqual(latest.id, runs[-1].id)

    def test_prefetched_reuses_cache_no_query(self):
        task, runs = self._task_with_runs(5)
        prefetched = Task.objects.prefetch_related("runs").get(pk=task.pk)

        with self.assertNumQueries(0):
            latest = prefetched.latest_run

        assert latest is not None
        self.assertEqual(latest.id, runs[-1].id)

    def test_prefetched_and_non_prefetched_return_same_row(self):
        task, runs = self._task_with_runs(3)
        non_prefetched = Task.objects.get(pk=task.pk).latest_run
        prefetched = Task.objects.prefetch_related("runs").get(pk=task.pk).latest_run

        assert non_prefetched is not None
        assert prefetched is not None
        self.assertEqual(non_prefetched.id, prefetched.id)
        self.assertEqual(non_prefetched.id, runs[-1].id)

    def test_latest_run_none_when_no_runs(self):
        task, _ = self._task_with_runs(0)
        self.assertIsNone(Task.objects.get(pk=task.pk).latest_run)
        self.assertIsNone(Task.objects.prefetch_related("runs").get(pk=task.pk).latest_run)


class TestConversationMinimalSerializerTaskField(APIBaseTest):
    def _task(self) -> Task:
        return Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )

    def test_minimal_serializer_exposes_task_latest_run_id(self):
        task = self._task()
        task.create_run(mode="interactive")
        Conversation.objects.create(
            user=self.user,
            team=self.team,
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
            task=task,
        )

        conversations = Conversation.objects.filter(task=task)
        data = ConversationMinimalSerializer(
            conversations, many=True, context={"team": self.team, "user": self.user}
        ).data

        self.assertEqual(data[0]["task"]["id"], str(task.id))
        latest_run = task.latest_run
        assert latest_run is not None
        self.assertEqual(data[0]["task"]["latest_run"], str(latest_run.id))
        self.assertEqual(data[0]["task"]["title"], "t")

    def test_minimal_serializer_task_null_for_langgraph(self):
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )
        data = ConversationMinimalSerializer(conversation, context={"team": self.team, "user": self.user}).data
        self.assertIsNone(data["task"])


class TestConversationSerializerArtifactEnrichment(APIBaseTest):
    """Test artifact enrichment functionality in the serializer."""

    def test_artifact_ref_message_enriched_in_response(self):
        """Test that ArtifactRefMessage is enriched with content from database artifact."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Artifact test conversation", type=Conversation.Type.ASSISTANT
        )

        # Create an artifact in the database
        artifact = AgentArtifact.objects.create(
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Chart Name"},
            conversation=conversation,
            team=self.team,
        )

        # Create state with an ArtifactRefMessage
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )
        state = AssistantState(messages=[artifact_message])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

            # The message should be enriched as an ArtifactMessage
            self.assertEqual(len(data["messages"]), 1)
            enriched_msg = data["messages"][0]
            self.assertEqual(enriched_msg["type"], "ai/artifact")
            self.assertEqual(enriched_msg["artifact_id"], artifact.short_id)
            self.assertEqual(enriched_msg["content"]["name"], "Chart Name")

    def test_artifact_ref_message_filtered_when_not_found(self):
        """Test that ArtifactRefMessage is filtered out when artifact not found in database."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Missing artifact conversation", type=Conversation.Type.ASSISTANT
        )

        # Create state with an ArtifactRefMessage pointing to non-existent artifact
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="nonexistent",
            source=ArtifactSource.ARTIFACT,
        )
        state = AssistantState(messages=[artifact_message])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

            # The message should be filtered out
            self.assertEqual(len(data["messages"]), 0)

    def test_mixed_messages_with_artifacts(self):
        """Test serialization with mixed message types including artifacts."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Mixed messages conversation", type=Conversation.Type.ASSISTANT
        )

        artifact = AgentArtifact.objects.create(
            name="Mixed Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Mixed Chart"},
            conversation=conversation,
            team=self.team,
        )

        # Create state with mixed message types
        assistant_message = AssistantMessage(content="Hello from assistant", type="ai")
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )
        state = AssistantState(messages=[assistant_message, artifact_message])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()
                tasks = []

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

            # Both messages should be included (AssistantMessage and enriched ArtifactMessage)
            self.assertEqual(len(data["messages"]), 2)
            self.assertEqual(data["messages"][0]["type"], "ai")
            self.assertEqual(data["messages"][0]["content"], "Hello from assistant")
            self.assertEqual(data["messages"][1]["type"], "ai/artifact")
            self.assertEqual(data["messages"][1]["content"]["name"], "Mixed Chart")
