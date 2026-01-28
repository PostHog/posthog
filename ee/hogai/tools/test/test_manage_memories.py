from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async

from products.posthog_ai.backend.models import AgentMemory

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.manage_memories import (
    CreateMemoryArgs,
    DeleteMemoryArgs,
    ListMetadataKeysArgs,
    ManageMemoriesTool,
    ManageMemoriesToolArgs,
    QueryMemoryArgs,
    UpdateMemoryArgs,
)
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestManageMemoriesToolArgs(NonAtomicBaseTest):
    """Test the discriminated union schema validation."""

    def test_create_action_parses_correctly(self):
        args = ManageMemoriesToolArgs(args={"action": "create", "contents": "test content"})
        assert isinstance(args.args, CreateMemoryArgs)
        self.assertEqual(args.args.contents, "test content")
        self.assertIsNone(args.args.metadata)

    def test_create_action_with_metadata(self):
        args = ManageMemoriesToolArgs(
            args={"action": "create", "contents": "test content", "metadata": {"type": "preference"}}
        )
        assert isinstance(args.args, CreateMemoryArgs)
        self.assertEqual(args.args.metadata, {"type": "preference"})

    def test_query_action_parses_correctly(self):
        args = ManageMemoriesToolArgs(args={"action": "query", "query_text": "find something"})
        assert isinstance(args.args, QueryMemoryArgs)
        self.assertEqual(args.args.query_text, "find something")
        self.assertTrue(args.args.user_only)
        self.assertEqual(args.args.limit, 10)

    def test_query_action_with_all_options(self):
        args = ManageMemoriesToolArgs(
            args={
                "action": "query",
                "query_text": "find something",
                "metadata_filter": {"type": "preference"},
                "user_only": False,
                "limit": 5,
            }
        )
        assert isinstance(args.args, QueryMemoryArgs)
        self.assertEqual(args.args.metadata_filter, {"type": "preference"})
        self.assertFalse(args.args.user_only)
        self.assertEqual(args.args.limit, 5)

    def test_update_action_parses_correctly(self):
        args = ManageMemoriesToolArgs(args={"action": "update", "memory_id": "123", "contents": "updated content"})
        assert isinstance(args.args, UpdateMemoryArgs)
        self.assertEqual(args.args.memory_id, "123")
        self.assertEqual(args.args.contents, "updated content")

    def test_delete_action_parses_correctly(self):
        args = ManageMemoriesToolArgs(args={"action": "delete", "memory_id_to_delete": "456"})
        assert isinstance(args.args, DeleteMemoryArgs)
        self.assertEqual(args.args.memory_id_to_delete, "456")

    def test_list_metadata_keys_action_parses_correctly(self):
        args = ManageMemoriesToolArgs(args={"action": "list_metadata_keys"})
        assert isinstance(args.args, ListMetadataKeysArgs)


class TestManageMemoriesTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = ManageMemoriesTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    async def test_create_memory(self):
        with patch.object(AgentMemory, "embed"):
            result, artifact = await self.tool._arun_impl(
                args=CreateMemoryArgs(action="create", contents="Test memory content", metadata={"type": "test"})
            )

        self.assertIn("Memory created successfully", result)
        self.assertIn("memory_id", artifact)
        self.assertEqual(artifact["action"], "created")

        memory = await sync_to_async(AgentMemory.objects.get)(id=artifact["memory_id"])
        self.assertEqual(memory.contents, "Test memory content")
        self.assertEqual(memory.metadata["type"], "test")
        self.assertEqual(memory.team_id, self.team.id)
        self.assertEqual(memory.user_id, self.user.id)

    async def test_update_memory(self):
        @sync_to_async
        def create_memory():
            return AgentMemory.objects.create(
                team=self.team,
                user=self.user,
                contents="Original content",
                metadata={"type": "original"},
            )

        memory = await create_memory()

        with patch.object(AgentMemory, "embed"):
            result, artifact = await self.tool._arun_impl(
                args=UpdateMemoryArgs(
                    action="update",
                    memory_id=str(memory.id),
                    contents="Updated content",
                    metadata={"type": "updated"},
                )
            )

        self.assertIn("updated successfully", result)
        self.assertEqual(artifact["action"], "updated")

        await sync_to_async(memory.refresh_from_db)()
        self.assertEqual(memory.contents, "Updated content")
        self.assertEqual(memory.metadata["type"], "updated")

    async def test_update_memory_not_found(self):
        fake_id = str(uuid4())
        with self.assertRaises(MaxToolRetryableError) as context:
            await self.tool._arun_impl(
                args=UpdateMemoryArgs(action="update", memory_id=fake_id, contents="New content")
            )
        self.assertIn("not found", str(context.exception))

    async def test_update_memory_requires_contents_or_metadata(self):
        @sync_to_async
        def create_memory():
            return AgentMemory.objects.create(
                team=self.team,
                user=self.user,
                contents="Original content",
                metadata={},
            )

        memory = await create_memory()

        with self.assertRaises(MaxToolRetryableError) as context:
            await self.tool._arun_impl(args=UpdateMemoryArgs(action="update", memory_id=str(memory.id)))
        self.assertIn("At least one of contents or metadata", str(context.exception))

    async def test_delete_memory(self):
        @sync_to_async
        def create_memory():
            return AgentMemory.objects.create(
                team=self.team,
                user=self.user,
                contents="To be deleted",
                metadata={},
            )

        memory = await create_memory()
        memory_id = str(memory.id)

        with patch.object(AgentMemory, "embed"):
            result, artifact = await self.tool._arun_impl(
                args=DeleteMemoryArgs(action="delete", memory_id_to_delete=memory_id)
            )

        self.assertIn("deleted successfully", result)
        self.assertEqual(artifact["action"], "deleted")
        exists = await sync_to_async(AgentMemory.objects.filter(id=memory_id).exists)()
        self.assertFalse(exists)

    async def test_delete_memory_not_found(self):
        fake_id = str(uuid4())
        with self.assertRaises(MaxToolRetryableError) as context:
            await self.tool._arun_impl(args=DeleteMemoryArgs(action="delete", memory_id_to_delete=fake_id))
        self.assertIn("not found", str(context.exception))

    async def test_list_metadata_keys_empty(self):
        result, artifact = await self.tool._arun_impl(args=ListMetadataKeysArgs(action="list_metadata_keys"))

        self.assertIn("No metadata keys found", result)
        self.assertEqual(artifact["keys"], [])

    async def test_list_metadata_keys_with_memories(self):
        @sync_to_async
        def create_memories():
            AgentMemory.objects.create(
                team=self.team,
                user=self.user,
                contents="Memory 1",
                metadata={"type": "preference", "category": "ui"},
            )
            AgentMemory.objects.create(
                team=self.team,
                user=self.user,
                contents="Memory 2",
                metadata={"type": "fact", "source": "user"},
            )

        await create_memories()

        result, artifact = await self.tool._arun_impl(args=ListMetadataKeysArgs(action="list_metadata_keys"))

        self.assertIn("Available metadata keys", result)
        self.assertEqual(sorted(artifact["keys"]), ["category", "source", "type"])

    async def test_query_memories_no_results(self):
        mock_result = MagicMock()
        mock_result.results = []

        with patch("ee.hogai.tools.manage_memories.execute_hogql_query", return_value=mock_result):
            result, artifact = await self.tool._arun_impl(
                args=QueryMemoryArgs(action="query", query_text="nonexistent")
            )

        self.assertIn("No memories found", result)
        self.assertEqual(artifact["results"], [])
        self.assertEqual(artifact["count"], 0)

    async def test_query_memories_with_results(self):
        import json

        mock_result = MagicMock()
        mock_result.results = [
            ("mem-1", "First memory content", json.dumps({"type": "test"}), 0.1),
            ("mem-2", "Second memory content", json.dumps({"type": "test"}), 0.2),
        ]

        with patch("ee.hogai.tools.manage_memories.execute_hogql_query", return_value=mock_result):
            result, artifact = await self.tool._arun_impl(args=QueryMemoryArgs(action="query", query_text="test query"))

        self.assertIn("Found 2 relevant memories", result)
        self.assertIn("First memory content", result)
        self.assertIn("Second memory content", result)
        self.assertEqual(artifact["count"], 2)
        self.assertEqual(len(artifact["results"]), 2)
        self.assertEqual(artifact["results"][0]["memory_id"], "mem-1")
        self.assertEqual(artifact["results"][1]["memory_id"], "mem-2")
