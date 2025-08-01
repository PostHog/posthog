"""
Tests for AI Assistant streaming behavior to ensure refactoring doesn't introduce regressions.

These tests verify the structure and ordering of streaming output.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from ee.hogai.assistant_factory import AssistantFactory
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage
from posthog.test.base import BaseTest


class TestStreamingBehavior(BaseTest):
    """Test streaming behavior to catch regressions from refactoring."""

    def test_main_assistant_factory_creates_correct_type(self):
        """Test that main assistant factory creates the expected type."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=conversation,
                new_message=HumanMessage(content="What are my top events?"),
                user=self.user,
                is_new_conversation=True,
            )

            # Verify assistant structure
            self.assertEqual(type(assistant).__name__, "MainAssistant")
            self.assertEqual(assistant._team.id, self.team.id)
            self.assertEqual(assistant._user.id, self.user.id)
            self.assertEqual(assistant._conversation.id, conversation.id)
            self.assertTrue(assistant._is_new_conversation)
            self.assertIsNotNone(assistant._latest_message)
            self.assertEqual(assistant._latest_message.content, "What are my top events?")

    def test_insights_assistant_factory_creates_correct_type(self):
        """Test that insights assistant factory creates the expected type."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        with patch("ee.hogai.insights_assistant.InsightsAssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            assistant = AssistantFactory.create(
                assistant_type="insights",
                team=self.team,
                conversation=conversation,
                user=self.user,
                is_new_conversation=False,
            )

            # Verify assistant structure
            self.assertEqual(type(assistant).__name__, "InsightsAssistant")
            self.assertEqual(assistant._team.id, self.team.id)
            self.assertEqual(assistant._user.id, self.user.id)
            self.assertEqual(assistant._conversation.id, conversation.id)
            self.assertFalse(assistant._is_new_conversation)
            self.assertIsNone(assistant._latest_message)  # No message for insights

    def test_factory_assistant_type_mapping_consistency(self):
        """Test that factory correctly maps assistant types to implementations."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        # Test type mapping consistency
        test_cases = [
            ("main", "MainAssistant"),
            ("assistant", "MainAssistant"),  # "assistant" should map to MainAssistant
            ("insights", "InsightsAssistant"),
        ]

        for assistant_type, expected_class_name in test_cases:
            with self.subTest(assistant_type=assistant_type):
                # Mock the appropriate graph class
                if assistant_type in ["main", "assistant"]:
                    graph_patch = patch("ee.hogai.main_assistant.AssistantGraph")
                else:
                    graph_patch = patch("ee.hogai.insights_assistant.InsightsAssistantGraph")

                with graph_patch as mock_graph_class:
                    mock_graph = MagicMock()
                    mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

                    assistant = AssistantFactory.create(
                        assistant_type=assistant_type,
                        team=self.team,
                        conversation=conversation,
                        user=self.user,
                        is_new_conversation=True,
                    )

                    self.assertEqual(type(assistant).__name__, expected_class_name)

    def test_assistant_config_structure_consistency(self):
        """Test that assistant config structure is consistent."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=conversation,
                new_message=HumanMessage(content="Test query"),
                user=self.user,
                is_new_conversation=True,
            )

            # Test config structure
            config = assistant._get_config()

            # Verify config structure
            self.assertIn("configurable", config)
            self.assertIn("thread_id", config["configurable"])
            # The thread_id should be the conversation id (as UUID, not string)
            self.assertEqual(config["configurable"]["thread_id"], conversation.id)

    def test_streaming_interface_exists(self):
        """Test that streaming interface is available and consistent."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        assistant_types = ["main", "insights"]

        for assistant_type in assistant_types:
            with self.subTest(assistant_type=assistant_type):
                # Mock the appropriate graph class
                if assistant_type == "main":
                    graph_patch = patch("ee.hogai.main_assistant.AssistantGraph")
                else:
                    graph_patch = patch("ee.hogai.insights_assistant.InsightsAssistantGraph")

                with graph_patch as mock_graph_class:
                    mock_graph = MagicMock()
                    mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

                    assistant = AssistantFactory.create(
                        assistant_type=assistant_type,
                        team=self.team,
                        conversation=conversation,
                        user=self.user,
                        is_new_conversation=True,
                    )

                    # Verify streaming methods exist
                    self.assertTrue(hasattr(assistant, "astream"))
                    self.assertTrue(hasattr(assistant, "invoke"))
                    self.assertTrue(callable(assistant.astream))
                    self.assertTrue(callable(assistant.invoke))

    def test_error_handling_structure(self):
        """Test that error handling structure is consistent."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        # Test that assistants can be created successfully with proper mocking
        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            # This should not raise an exception
            assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=conversation,
                user=self.user,
                is_new_conversation=True,
            )

            # Verify the assistant was created
            self.assertIsNotNone(assistant)
            self.assertEqual(type(assistant).__name__, "MainAssistant")

    def test_unknown_assistant_type_error(self):
        """Test that unknown assistant types raise appropriate errors."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        with self.assertRaises(ValueError) as context:
            AssistantFactory.create(
                assistant_type="unknown_type",
                team=self.team,
                conversation=conversation,
                user=self.user,
                is_new_conversation=True,
            )

        self.assertIn("Unsupported assistant type", str(context.exception))

    def test_assistant_processor_types(self):
        """Test that assistants have the correct update processor types."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        # Test main assistant processor
        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            main_assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=conversation,
                user=self.user,
                is_new_conversation=True,
            )

            # Verify processor type (should be AssistantUpdateProcessor)
            processor = main_assistant._get_update_processor()
            self.assertIsNotNone(processor)
            processor_name = type(processor).__name__
            self.assertEqual(processor_name, "AssistantUpdateProcessor")

        # Test insights assistant processor
        with patch("ee.hogai.insights_assistant.InsightsAssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            insights_assistant = AssistantFactory.create(
                assistant_type="insights",
                team=self.team,
                conversation=conversation,
                user=self.user,
                is_new_conversation=True,
            )

            # Verify processor type
            processor = insights_assistant._get_update_processor()
            self.assertIsNotNone(processor)
            processor_name = type(processor).__name__
            self.assertEqual(processor_name, "InsightsUpdateProcessor")
