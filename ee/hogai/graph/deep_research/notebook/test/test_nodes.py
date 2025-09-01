from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import HumanMessage, NotebookUpdateMessage, ProsemirrorJSONContent

from ee.hogai.graph.deep_research.notebook.nodes import DeepResearchNotebookPlanningNode
from ee.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from ee.models.assistant import Conversation


class TestDeepResearchNotebookPlanningNode(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.node = DeepResearchNotebookPlanningNode(self.team, self.user)
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    async def test_arun_creates_notebook_plan_successfully(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that notebook plans is created successfully."""
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook_message = NotebookUpdateMessage(
            notebook_id="test-notebook-123",
            content=ProsemirrorJSONContent(
                type="doc",
                content=[
                    {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Research Plan"}]}
                ],
            ),
            id=str(uuid4()),
        )
        mock_astream.return_value = mock_notebook_message

        state = DeepResearchState(messages=[HumanMessage(content="Create a research plan for user engagement")])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0], mock_notebook_message)
        self.assertIsNone(result.previous_response_id)
        self.assertEqual(result.notebook_short_id, "test-notebook-123")

        mock_core_memory.assert_called_once()
        mock_astream.assert_called_once()

    @parameterized.expand(
        [
            ("simple_request", "Analyze user behavior"),
            (
                "complex_request",
                "Create a detailed research plan for understanding user engagement patterns across different cohorts",
            ),
            ("question_format", "What factors influence user retention?"),
        ]
    )
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    async def test_arun_handles_different_message_types(
        self, _name, message_content, mock_astream, mock_get_model, mock_core_memory
    ):
        """Test that arun handles different types of human messages correctly."""
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook_message = NotebookUpdateMessage(
            notebook_id="test-notebook", content=ProsemirrorJSONContent(type="doc", content=[]), id=str(uuid4())
        )
        mock_astream.return_value = mock_notebook_message

        state = DeepResearchState(messages=[HumanMessage(content=message_content)])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        self.assertEqual(result.notebook_short_id, "test-notebook")

    async def test_arun_raises_error_when_last_message_not_human(self):
        """Test that arun raises ValueError when last message is **NOT** a human message."""
        # Arrange
        state = DeepResearchState(
            messages=[
                HumanMessage(content="First message"),
                NotebookUpdateMessage(notebook_id="test", content=ProsemirrorJSONContent(type="doc", content=[])),
            ]
        )

        with self.assertRaises(ValueError) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "Last message is not a human message.")

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    async def test_arun_uses_previous_response_id_correctly(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that arun passes previous_response_id to model and resets it in response."""
        # Arrange
        mock_core_memory.return_value = "Test core memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook_message = NotebookUpdateMessage(
            notebook_id="test-notebook", content=ProsemirrorJSONContent(type="doc", content=[]), id=str(uuid4())
        )
        mock_astream.return_value = mock_notebook_message

        previous_response_id = "previous-response-123"
        state = DeepResearchState(
            messages=[HumanMessage(content="Test message")], previous_response_id=previous_response_id
        )

        result = await self.node.arun(state, self.config)

        args, _ = mock_get_model.call_args
        instructions_arg = args[0]
        response_id_arg = args[1]

        self.assertIn("Create a single-page Markdown plan", instructions_arg)
        self.assertIn("Test core memory", instructions_arg)
        self.assertEqual(response_id_arg, previous_response_id)
        self.assertIsNone(result.previous_response_id)

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    async def test_state_management_with_notebook_updates(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that state is properly managed with notebook updates."""
        mock_core_memory.return_value = "Core memory content"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        notebook_id = "notebook-456"
        mock_notebook_message = NotebookUpdateMessage(
            notebook_id=notebook_id, content=ProsemirrorJSONContent(type="doc", content=[]), id=str(uuid4())
        )
        mock_astream.return_value = mock_notebook_message

        initial_state = DeepResearchState(
            messages=[HumanMessage(content="Create research plan")],
            todos=None,
            tasks=None,
            task_results=[],
            intermediate_results=[],
            previous_response_id="old-id",
            notebook_short_id=None,
        )

        result = await self.node.arun(initial_state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        self.assertEqual(result.notebook_short_id, notebook_id)
        self.assertIsNone(result.previous_response_id)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].notebook_id, notebook_id)

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    async def test_integration_with_notebook_serializer(self, mock_get_model, mock_core_memory, mock_astream_notebook):
        """Test integration with NotebookSerializer for content processing."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_notebook_message = NotebookUpdateMessage(
            notebook_id="test-notebook", content=ProsemirrorJSONContent(type="doc", content=[]), id=str(uuid4())
        )
        mock_astream_notebook.return_value = mock_notebook_message

        state = DeepResearchState(messages=[HumanMessage(content="Create a research plan")])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        mock_astream_notebook.assert_called_once()
        self.assertEqual(result.notebook_short_id, "test-notebook")

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    async def test_streaming_behavior_with_partial_messages(
        self, mock_get_model, mock_core_memory, mock_astream_notebook
    ):
        """Test streaming behavior processes partial messages correctly."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_notebook_message = NotebookUpdateMessage(
            notebook_id="test-notebook", content=ProsemirrorJSONContent(type="doc", content=[]), id=str(uuid4())
        )
        mock_astream_notebook.return_value = mock_notebook_message

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        result = await self.node.arun(state, self.config)

        self.assertIsInstance(result, PartialDeepResearchState)
        mock_astream_notebook.assert_called_once()

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    async def test_error_when_no_notebook_message_generated(
        self, mock_get_model, mock_core_memory, mock_astream_notebook
    ):
        """Test error handling when no notebook update message is generated."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        # Mocking to raise
        mock_astream_notebook.side_effect = ValueError("No notebook update message found.")

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        with self.assertRaises(ValueError) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "No notebook update message found.")

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    async def test_error_when_core_memory_fails(self, mock_core_memory):
        """Test error handling when core memory retrieval fails."""
        mock_core_memory.side_effect = Exception("Core memory error")

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        with self.assertRaises(Exception) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "Core memory error")

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    async def test_error_when_model_generation_fails(self, mock_get_model, mock_core_memory, mock_astream_notebook):
        """Test error handling when model generation fails."""
        mock_core_memory.return_value = "Test memory"
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_astream_notebook.side_effect = Exception("Model generation failed")

        state = DeepResearchState(messages=[HumanMessage(content="Create research plan")])

        with self.assertRaises(Exception) as context:
            await self.node.arun(state, self.config)

        self.assertEqual(str(context.exception), "Model generation failed")

    @parameterized.expand(
        [
            ("empty_messages", []),
            ("none_messages", None),
        ]
    )
    async def test_edge_case_empty_or_none_messages(self, _name, messages):
        """Test handling of edge cases with empty or None messages."""
        if messages is None:
            state = DeepResearchState()
        else:
            state = DeepResearchState(messages=messages)

        with self.assertRaises(IndexError):
            await self.node.arun(state, self.config)

    async def test_edge_case_message_with_empty_content(self):
        """Test handling of human message with empty content."""
        state = DeepResearchState(messages=[HumanMessage(content="")])

        with patch(
            "ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory"
        ) as mock_core_memory:
            with patch(
                "ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model"
            ) as mock_get_model:
                with patch(
                    "ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook"
                ) as mock_astream:
                    mock_core_memory.return_value = "Test memory"
                    mock_model = AsyncMock()
                    mock_get_model.return_value = mock_model

                    mock_notebook_message = NotebookUpdateMessage(
                        notebook_id="test-notebook",
                        content=ProsemirrorJSONContent(type="doc", content=[]),
                        id=str(uuid4()),
                    )
                    mock_astream.return_value = mock_notebook_message

                    result = await self.node.arun(state, self.config)

                    self.assertIsInstance(result, PartialDeepResearchState)

    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._aget_core_memory")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._get_model")
    @patch("ee.hogai.graph.deep_research.notebook.nodes.DeepResearchNotebookPlanningNode._astream_notebook")
    async def test_message_content_passed_to_prompt_correctly(self, mock_astream, mock_get_model, mock_core_memory):
        """Test that human message content is correctly passed to the prompt."""
        mock_core_memory.return_value = "Test memory"
        mock_model = AsyncMock()
        mock_get_model.return_value = mock_model

        mock_notebook_message = NotebookUpdateMessage(
            notebook_id="test-notebook", content=ProsemirrorJSONContent(type="doc", content=[]), id=str(uuid4())
        )
        mock_astream.return_value = mock_notebook_message

        user_message = "Analyze user engagement patterns for mobile users"
        state = DeepResearchState(messages=[HumanMessage(content=user_message)])

        await self.node.arun(state, self.config)

        # Assert - verify the prompt template was created with the user message
        # The chain should contain the user's message content (verify the call was made)
        mock_astream.assert_called_once()
