"""
Comprehensive test suite for the MigratingDjangoCheckpointer.

Tests the automatic migration of legacy AssistantState checkpoints to
graph-specific states (AssistantGraphState, InsightsGraphState).
"""

from langgraph.checkpoint.base.id import uuid6

from ee.hogai.django_checkpoint.migrating_checkpointer import MigratingDjangoCheckpointer
from ee.hogai.utils.graph_states import AssistantGraphState, InsightsGraphState
from ee.models.assistant import Conversation
from posthog.test.base import NonAtomicBaseTest


class TestMigratingDjangoCheckpointer(NonAtomicBaseTest):
    """Test suite for checkpoint migration functionality."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.checkpointer = MigratingDjangoCheckpointer()

    async def test_get_target_state_type_for_root_namespace(self):
        """Test that root namespace (empty string) maps to AssistantGraphState."""
        target_type = self.checkpointer._get_target_state_type("")
        self.assertEqual(target_type, AssistantGraphState)

    async def test_get_target_state_type_for_insights_namespace(self):
        """Test that insights namespace maps to InsightsGraphState."""
        target_type = self.checkpointer._get_target_state_type("insights")
        self.assertEqual(target_type, InsightsGraphState)

        target_type = self.checkpointer._get_target_state_type("insights_subgraph")
        self.assertEqual(target_type, InsightsGraphState)

    async def test_get_target_state_type_for_unknown_namespace(self):
        """Test that unknown namespaces default to AssistantGraphState."""
        target_type = self.checkpointer._get_target_state_type("unknown_graph")
        self.assertEqual(target_type, AssistantGraphState)

    async def test_migrate_legacy_assistant_state_to_assistant_graph_state(self):
        """Test migration of legacy AssistantState to AssistantGraphState."""
        # Create legacy checkpoint data (simulating old AssistantState)
        legacy_state_data = {
            "messages": [{"type": "human", "content": "Hello"}, {"type": "assistant", "content": "Hi there!"}],
            "start_id": "msg-123",
            "root_tool_call_id": "tool-456",
            "root_tool_calls_count": 1,
            "graph_status": "resumed",
            # Legacy fields that should be preserved for parent graph
            "onboarding_question": "What can I help you with?",
            "search_insights_query": "user behavior trends",
            # Legacy fields that should be dropped (insights-specific)
            "plan": "This should be dropped",
            "intermediate_steps": [("action", "result")],
            "rag_context": "This should be dropped",
            "query_generation_retry_count": 2,
        }

        checkpoint_data = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {"__start__": legacy_state_data},
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for root namespace (AssistantGraphState)
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_data, "")

        # Verify migration occurred
        migrated_state = migrated_data["channel_values"]["__start__"]

        # Should preserve AssistantGraphState fields
        self.assertEqual(migrated_state["messages"], legacy_state_data["messages"])
        self.assertEqual(migrated_state["start_id"], "msg-123")
        self.assertEqual(migrated_state["root_tool_call_id"], "tool-456")
        self.assertEqual(migrated_state["root_tool_calls_count"], 1)
        self.assertEqual(migrated_state["graph_status"], "resumed")
        self.assertEqual(migrated_state["onboarding_question"], "What can I help you with?")
        self.assertEqual(migrated_state["search_insights_query"], "user behavior trends")

        # Should drop InsightsGraphState-specific fields
        self.assertNotIn("plan", migrated_state)
        self.assertNotIn("intermediate_steps", migrated_state)
        self.assertNotIn("rag_context", migrated_state)
        self.assertNotIn("query_generation_retry_count", migrated_state)

    async def test_migrate_legacy_assistant_state_to_insights_graph_state(self):
        """Test migration of legacy AssistantState to InsightsGraphState."""
        # Create legacy checkpoint data with insights-specific fields
        legacy_state_data = {
            "messages": [
                {"type": "human", "content": "Show me trends"},
                {"type": "assistant", "content": "Creating trends chart..."},
            ],
            "graph_status": "interrupted",
            "plan": "Create a trends query for page views",
            "intermediate_steps": [("query_planning", "trends query created")],
            "rag_context": "Page views are tracked events...",
            "query_generation_retry_count": 1,
            "root_tool_insight_plan": "Generate trends insight",
            "root_tool_insight_type": "trends",
            # Parent-specific fields that should be dropped
            "start_id": "msg-789",
            "root_tool_call_id": "tool-abc",
            "onboarding_question": "This should be dropped",
            "search_insights_query": "This should be dropped",
        }

        checkpoint_data = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {"insights_state": legacy_state_data},
            "channel_versions": {"insights_state": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for insights namespace
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_data, "insights")

        # Verify migration occurred
        migrated_state = migrated_data["channel_values"]["insights_state"]

        # Should preserve InsightsGraphState fields
        self.assertEqual(migrated_state["messages"], legacy_state_data["messages"])
        self.assertEqual(migrated_state["graph_status"], "interrupted")
        self.assertEqual(migrated_state["plan"], "Create a trends query for page views")
        self.assertEqual(migrated_state["intermediate_steps"], [("query_planning", "trends query created")])
        self.assertEqual(migrated_state["rag_context"], "Page views are tracked events...")
        self.assertEqual(migrated_state["query_generation_retry_count"], 1)
        self.assertEqual(migrated_state["root_tool_insight_plan"], "Generate trends insight")
        self.assertEqual(migrated_state["root_tool_insight_type"], "trends")

        # Should drop AssistantGraphState-specific fields
        self.assertNotIn("start_id", migrated_state)
        self.assertNotIn("root_tool_call_id", migrated_state)
        self.assertNotIn("onboarding_question", migrated_state)
        self.assertNotIn("search_insights_query", migrated_state)

    async def test_no_migration_needed_for_already_migrated_state(self):
        """Test that already-migrated states are not re-migrated."""
        # Create properly structured AssistantGraphState data
        assistant_state_data = {
            "messages": [{"type": "human", "content": "Hello"}],
            "start_id": "msg-123",
            "graph_status": None,
            # Only fields that exist in AssistantGraphState
        }

        checkpoint_data = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {"__start__": assistant_state_data},
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for root namespace
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_data, "")

        # Should be unchanged (no migration needed)
        self.assertEqual(migrated_data, checkpoint_data)

    async def test_empty_checkpoint_data_handling(self):
        """Test handling of empty or invalid checkpoint data."""
        # Empty checkpoint data
        empty_data = {}
        result = self.checkpointer._migrate_checkpoint_data(empty_data, "")
        self.assertEqual(result, empty_data)

        # Checkpoint with no channel_values
        no_channels = {"v": 1, "id": str(uuid6())}
        result = self.checkpointer._migrate_checkpoint_data(no_channels, "")
        self.assertEqual(result, no_channels)

        # Checkpoint with empty channel_values
        empty_channels = {"v": 1, "id": str(uuid6()), "channel_values": {}}
        result = self.checkpointer._migrate_checkpoint_data(empty_channels, "")
        self.assertEqual(result, empty_channels)

    async def test_aget_tuple_with_migration(self):
        """Test that aget_tuple automatically migrates legacy checkpoints."""
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)

        # Create a legacy checkpoint with mixed state fields
        legacy_checkpoint = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6()),
            "channel_values": {
                "__start__": {
                    "messages": [
                        {"type": "human", "content": "Create insights"},
                        {"type": "assistant", "content": "I'll help with that"},
                    ],
                    "start_id": "msg-start",
                    "graph_status": "resumed",
                    # Mixed legacy fields - some should be kept, some dropped
                    "root_tool_call_id": "tool-123",
                    "plan": "Should be dropped for root graph",
                    "intermediate_steps": [("action", "result")],
                }
            },
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        metadata = {"source": "test_migration"}
        config = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": ""}}

        # Save using regular checkpointer first
        await super(MigratingDjangoCheckpointer, self.checkpointer).aput(config, legacy_checkpoint, metadata, {})

        # Retrieve using migrating checkpointer
        retrieved_tuple = await self.checkpointer.aget_tuple(config)

        self.assertIsNotNone(retrieved_tuple)
        migrated_state = retrieved_tuple.checkpoint["channel_values"]["__start__"]

        # Should have migrated to AssistantGraphState structure
        self.assertIn("messages", migrated_state)
        self.assertIn("start_id", migrated_state)
        self.assertIn("root_tool_call_id", migrated_state)
        self.assertEqual(migrated_state["graph_status"], "resumed")

        # Should have dropped insights-specific fields
        self.assertNotIn("plan", migrated_state)
        self.assertNotIn("intermediate_steps", migrated_state)

    async def test_alist_with_migration(self):
        """Test that alist automatically migrates all legacy checkpoints."""
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)

        # Create multiple legacy checkpoints
        legacy_checkpoints = []
        for i in range(3):
            checkpoint = {
                "v": 1,
                "ts": "2024-07-31T20:14:19.804150+00:00",
                "id": str(uuid6()),
                "channel_values": {
                    "__start__": {
                        "messages": [{"type": "human", "content": f"Message {i}"}],
                        "start_id": f"msg-{i}",
                        "graph_status": None,
                        "plan": f"Plan {i} - should be dropped",
                        "root_tool_call_id": f"tool-{i}",
                    }
                },
                "channel_versions": {"__start__": 1},
                "versions_seen": {},
                "pending_sends": [],
            }
            legacy_checkpoints.append(checkpoint)

        config = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": ""}}

        # Save all checkpoints using regular checkpointer
        for i, checkpoint in enumerate(legacy_checkpoints):
            await super(MigratingDjangoCheckpointer, self.checkpointer).aput(config, checkpoint, {"step": i}, {})

        # List using migrating checkpointer
        retrieved_checkpoints = [checkpoint_tuple async for checkpoint_tuple in self.checkpointer.alist(config)]

        self.assertEqual(len(retrieved_checkpoints), 3)

        # Verify all checkpoints were migrated
        for _i, checkpoint_tuple in enumerate(retrieved_checkpoints):
            migrated_state = checkpoint_tuple.checkpoint["channel_values"]["__start__"]

            self.assertIn("messages", migrated_state)
            self.assertIn("start_id", migrated_state)
            self.assertIn("root_tool_call_id", migrated_state)

            # Should have dropped insights-specific fields
            self.assertNotIn("plan", migrated_state)

    async def test_migration_with_insights_namespace(self):
        """Test migration specifically for insights subgraph namespace."""
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)

        # Create legacy checkpoint with insights-focused data
        legacy_checkpoint = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6()),
            "channel_values": {
                "insights_channel": {
                    "messages": [
                        {"type": "human", "content": "Show trends"},
                        {"type": "assistant", "content": "Analyzing trends..."},
                    ],
                    "graph_status": "interrupted",
                    "plan": "Create trends visualization",
                    "intermediate_steps": [("retrieve_data", "success")],
                    "rag_context": "Trends context...",
                    "query_generation_retry_count": 2,
                    # Parent fields that should be dropped
                    "start_id": "should-be-dropped",
                    "root_tool_call_id": "should-be-dropped",
                }
            },
            "channel_versions": {"insights_channel": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        metadata = {"source": "insights_test"}
        config = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": "insights_subgraph"}}

        # Save using regular checkpointer
        await super(MigratingDjangoCheckpointer, self.checkpointer).aput(config, legacy_checkpoint, metadata, {})

        # Retrieve using migrating checkpointer
        retrieved_tuple = await self.checkpointer.aget_tuple(config)

        self.assertIsNotNone(retrieved_tuple)
        migrated_state = retrieved_tuple.checkpoint["channel_values"]["insights_channel"]

        # Should have migrated to InsightsGraphState structure
        self.assertIn("messages", migrated_state)
        self.assertEqual(migrated_state["graph_status"], "interrupted")
        self.assertEqual(migrated_state["plan"], "Create trends visualization")
        self.assertEqual(migrated_state["intermediate_steps"], [("retrieve_data", "success")])
        self.assertEqual(migrated_state["rag_context"], "Trends context...")
        self.assertEqual(migrated_state["query_generation_retry_count"], 2)

        # Should have dropped parent-specific fields
        self.assertNotIn("start_id", migrated_state)
        self.assertNotIn("root_tool_call_id", migrated_state)

    async def test_migration_preserves_message_structure(self):
        """Test that message structure is correctly preserved during migration."""
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)

        # Create checkpoint with complex message structure
        complex_messages = [
            {"type": "human", "content": "Show me funnel analysis", "id": "human-msg-1"},
            {"type": "assistant", "content": "I'll create a funnel analysis for you.", "id": "assistant-msg-1"},
            {"type": "visualization", "content": "Funnel chart data...", "id": "viz-msg-1"},
        ]

        legacy_checkpoint = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6()),
            "channel_values": {
                "__start__": {
                    "messages": complex_messages,
                    "start_id": "human-msg-1",
                    "graph_status": None,
                    "plan": "Should be dropped",
                }
            },
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        config = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": ""}}

        # Save and retrieve
        await super(MigratingDjangoCheckpointer, self.checkpointer).aput(config, legacy_checkpoint, {}, {})

        retrieved_tuple = await self.checkpointer.aget_tuple(config)
        migrated_state = retrieved_tuple.checkpoint["channel_values"]["__start__"]

        # Messages should be preserved exactly
        self.assertEqual(migrated_state["messages"], complex_messages)
        self.assertEqual(migrated_state["start_id"], "human-msg-1")

    async def test_migration_error_handling(self):
        """Test error handling when migration encounters invalid data."""
        # Create checkpoint with invalid state data
        invalid_checkpoint = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {
                "__start__": "invalid_state_data"  # Should be dict, not string
            },
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migration should handle this gracefully and return original data
        migrated_data = self.checkpointer._migrate_checkpoint_data(invalid_checkpoint, "")

        # Should return original data unchanged when migration fails
        self.assertEqual(migrated_data, invalid_checkpoint)

    async def test_migration_with_multiple_channels(self):
        """Test migration when checkpoint has multiple state channels."""
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)

        # Create checkpoint with multiple channels, only one with state data
        checkpoint_with_multiple_channels = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6()),
            "channel_values": {
                "branch:to:node1": None,
                "messages": ["Hello", "Hi there"],
                "__start__": {
                    "messages": [{"type": "human", "content": "Hello"}],
                    "start_id": "msg-1",
                    "graph_status": None,
                    "plan": "Should be dropped for root",
                },
                "other_channel": {"not": "state_data"},
            },
            "channel_versions": {"branch:to:node1": 1, "messages": 2, "__start__": 1, "other_channel": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        config = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": ""}}

        # Save using regular checkpointer
        await super(MigratingDjangoCheckpointer, self.checkpointer).aput(
            config, checkpoint_with_multiple_channels, {}, {}
        )

        # Retrieve using migrating checkpointer
        retrieved_tuple = await self.checkpointer.aget_tuple(config)

        # Should only migrate the state channel (__start__)
        migrated_channels = retrieved_tuple.checkpoint["channel_values"]

        # State channel should be migrated
        self.assertIn("messages", migrated_channels["__start__"])
        self.assertNotIn("plan", migrated_channels["__start__"])

        # Other channels should be unchanged
        self.assertIsNone(migrated_channels["branch:to:node1"])
        self.assertEqual(migrated_channels["messages"], ["Hello", "Hi there"])
        self.assertEqual(migrated_channels["other_channel"]["not"], "state_data")

    async def test_concurrent_migration_operations(self):
        """Test that concurrent migration operations work correctly."""
        import asyncio

        thread = await Conversation.objects.acreate(user=self.user, team=self.team)

        # Create multiple legacy checkpoints
        checkpoint_configs = []
        for i in range(5):
            checkpoint = {
                "v": 1,
                "ts": "2024-07-31T20:14:19.804150+00:00",
                "id": str(uuid6()),
                "channel_values": {
                    "__start__": {
                        "messages": [{"type": "human", "content": f"Message {i}"}],
                        "start_id": f"msg-{i}",
                        "graph_status": None,
                        "plan": f"Plan {i}",
                        "root_tool_call_id": f"tool-{i}",
                    }
                },
                "channel_versions": {"__start__": 1},
                "versions_seen": {},
                "pending_sends": [],
            }

            config = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": ""}}

            # Save using regular checkpointer
            await super(MigratingDjangoCheckpointer, self.checkpointer).aput(config, checkpoint, {"step": i}, {})

            checkpoint_configs.append(config)

        # Retrieve all checkpoints concurrently
        async def get_checkpoint(config):
            return await self.checkpointer.aget_tuple(config)

        results = await asyncio.gather(*[get_checkpoint(config) for config in checkpoint_configs])

        # All should be successfully migrated
        self.assertEqual(len(results), 5)
        for result in results:
            self.assertIsNotNone(result)
            migrated_state = result.checkpoint["channel_values"]["__start__"]
            self.assertIn("messages", migrated_state)
            self.assertIn("root_tool_call_id", migrated_state)
            self.assertNotIn("plan", migrated_state)
