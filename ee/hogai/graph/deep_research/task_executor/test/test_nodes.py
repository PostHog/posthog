import uuid
from unittest.mock import MagicMock, patch
from parameterized import parameterized

from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.deep_research.task_executor.nodes import TaskExecutorNode
from ee.hogai.graph.deep_research.types import (
    DeepResearchState,
    DeepResearchSingleTaskResult,
    PartialDeepResearchState,
)
from ee.hogai.utils.types.base import InsightArtifact
from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    HumanMessage,
    ReasoningMessage,
    TaskExecutionItem,
    TaskExecutionMessage,
    TaskExecutionStatus,
)
from unittest import TestCase


class TestTaskExecutorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_team.name = "Test Team"
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.email = "test@example.com"

        self.mock_insights_subgraph = MagicMock()
        self.node = TaskExecutorNode(self.mock_team, self.mock_user, self.mock_insights_subgraph)

    def _create_task_execution_item(
        self,
        task_id: str | None = None,
        description: str = "Test task",
        prompt: str = "Test prompt",
        status: TaskExecutionStatus = TaskExecutionStatus.PENDING,
        artifact_ids: list[str] | None = None,
        progress_text: str | None = None,
    ) -> TaskExecutionItem:
        return TaskExecutionItem(
            id=task_id or str(uuid.uuid4()),
            description=description,
            prompt=prompt,
            status=status,
            artifact_ids=artifact_ids,
            progress_text=progress_text,
        )

    def _create_insight_artifact(
        self,
        artifact_id: str | None = None,
        description: str = "Test artifact",
        query: str = "Test query",
    ) -> InsightArtifact:
        return InsightArtifact(
            id=artifact_id or str(uuid.uuid4()),
            description=description,
            query=query,
        )

    def _create_assistant_message_with_tool_calls(self, tool_call_id: str = "test_tool_call") -> AssistantMessage:
        return AssistantMessage(
            content="Test message",
            tool_calls=[
                AssistantToolCall(
                    id=tool_call_id,
                    name="test_tool",
                    args={"test": "args"},
                )
            ],
        )

    def _create_state_with_tasks(
        self,
        tasks: list[TaskExecutionItem] | None = None,
        messages: list | None = None,
        task_results: list[DeepResearchSingleTaskResult] | None = None,
    ) -> DeepResearchState:
        if tasks is None:
            tasks = [self._create_task_execution_item()]
        if messages is None:
            messages = [self._create_assistant_message_with_tool_calls()]
        if task_results is None:
            task_results = []

        return DeepResearchState(
            messages=messages,
            tasks=tasks,
            task_results=task_results,
        )


class TestTaskExecutorNodeInitialization(TestTaskExecutorNode):
    def test_node_initializes_with_insights_subgraph(self):
        """Test that TaskExecutorNode initializes correctly with insights subgraph."""
        self.assertIsNotNone(self.node)
        self.assertEqual(self.node._team, self.mock_team)
        self.assertEqual(self.node._user, self.mock_user)
        self.assertIsNotNone(self.node._execute_tasks_tool)
        self.assertEqual(self.node._execute_tasks_tool._insights_subgraph, self.mock_insights_subgraph)


class TestTaskExecutorNodeArun(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    async def test_arun_with_valid_tool_call_and_tasks(self, mock_get_stream_writer):
        """Test successful execution with valid tool call message and tasks."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        task = self._create_task_execution_item()
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        expected_result = PartialDeepResearchState(
            messages=[AssistantToolCallMessage(content="Test result", tool_call_id="test_tool_call")]
        )
        with patch.object(self.node, "_execute_tasks", return_value=expected_result) as mock_execute:
            result = await self.node.arun(state, config)

            self.assertEqual(result, expected_result)
            mock_execute.assert_called_once_with(state, config, "test_tool_call")

    async def test_arun_raises_error_for_missing_tool_call_message(self):
        """Test that we raise ValueError when no tool call message is found."""
        state = DeepResearchState(
            messages=[HumanMessage(content="Test")],  # No AssistantMessage with tool_calls
            tasks=[self._create_task_execution_item()],
        )
        config = RunnableConfig()

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, config)

        self.assertEqual(str(cm.exception), "No tool call message found")

    async def test_arun_raises_error_for_assistant_message_without_tool_calls(self):
        """Test that arun raises ValueError when AssistantMessage has no tool_calls."""
        state = DeepResearchState(
            messages=[AssistantMessage(content="Test message")],  # No tool_calls
            tasks=[self._create_task_execution_item()],
        )
        config = RunnableConfig()

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, config)

        self.assertEqual(str(cm.exception), "No tool call message found")

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.logger")
    async def test_arun_handles_empty_task_list(self, mock_logger):
        """Test that arun handles empty task lists gracefully."""
        state = DeepResearchState(
            messages=[self._create_assistant_message_with_tool_calls()],
            tasks=None,  # Empty tasks
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        self.assertIsInstance(result, PartialDeepResearchState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].content, "No tasks to execute")
        self.assertEqual(result.messages[0].tool_call_id, "test_tool_call")
        mock_logger.warning.assert_called_once_with("No research step provided to execute")


class TestTaskExecutorNodeExecuteTasks(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    @patch("uuid.uuid4")
    async def test_execute_tasks_successful_execution(self, mock_uuid, mock_get_stream_writer):
        """Test successful task execution with proper message flow."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer
        mock_uuid.return_value.hex = "test_uuid"
        mock_uuid.return_value.__str__ = lambda _: "test_uuid"

        task = self._create_task_execution_item(task_id="task_1")
        artifact = self._create_insight_artifact(artifact_id="artifact_1")

        state = self._create_state_with_tasks(
            tasks=[task],
            task_results=[
                DeepResearchSingleTaskResult(
                    id="prev_task",
                    description="Previous task",
                    result="Previous result",
                    artifacts=[artifact],
                    status=TaskExecutionStatus.COMPLETED,
                )
            ],
        )
        config = RunnableConfig()

        # Mock the streaming execution
        mock_task_result = DeepResearchSingleTaskResult(
            id="task_1",
            description="Test task",
            result="Task completed successfully",
            artifacts=[artifact],
            status=TaskExecutionStatus.COMPLETED,
        )

        async def mock_astream(input_tuples, config):
            yield ReasoningMessage(content="Starting task execution")
            yield mock_task_result

        with patch.object(self.node._execute_tasks_tool, "astream", side_effect=mock_astream):
            result = await self.node._execute_tasks(state, config, "test_tool_call")

            self.assertIsInstance(result, PartialDeepResearchState)
            self.assertEqual(len(result.messages), 2)

            self.assertIsInstance(result.messages[0], TaskExecutionMessage)

            self.assertIsInstance(result.messages[1], AssistantToolCallMessage)
            self.assertEqual(result.messages[1].tool_call_id, "test_tool_call")
            self.assertIn("Task completed successfully", result.messages[1].content)

            self.assertEqual(len(result.task_results), 1)
            self.assertEqual(result.task_results[0], mock_task_result)

            self.assertIsNone(result.tasks)

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    async def test_execute_tasks_handles_empty_tasks(self, mock_get_stream_writer):
        """Test that _execute_tasks raises ValueError for empty tasks."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        state = DeepResearchState(
            messages=[self._create_assistant_message_with_tool_calls()],
            tasks=[],  # Empty task list
        )
        config = RunnableConfig()

        with self.assertRaises(ValueError) as cm:
            await self.node._execute_tasks(state, config, "test_tool_call")

        self.assertEqual(str(cm.exception), "No tasks to execute")

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.capture_exception")
    async def test_execute_tasks_handles_exceptions(self, mock_capture, mock_get_stream_writer):
        """Test that _execute_tasks properly handles and re-raises exceptions."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        task = self._create_task_execution_item()
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        test_exception = Exception("Test exception")

        with patch.object(self.node._execute_tasks_tool, "astream", side_effect=test_exception):
            with self.assertRaises(Exception) as cm:
                await self.node._execute_tasks(state, config, "test_tool_call")

            self.assertEqual(cm.exception, test_exception)
            mock_capture.assert_called_once_with(test_exception)


class TestTaskExecutorNodeStreamingBehavior(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    @patch("uuid.uuid4")
    async def test_streaming_with_reasoning_messages(self, mock_uuid, mock_get_stream_writer):
        """Test that reasoning messages are properly streamed during execution."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer
        mock_uuid.return_value.__str__ = lambda _: "test_uuid"

        task = self._create_task_execution_item()
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        async def mock_astream(input_tuples, config):
            yield ReasoningMessage(content="Planning approach")
            yield ReasoningMessage(content="Executing query")
            yield DeepResearchSingleTaskResult(
                id=task.id,
                description="Test task",
                result="Success",
                artifacts=[],
                status=TaskExecutionStatus.COMPLETED,
            )

        with patch.object(self.node._execute_tasks_tool, "astream", side_effect=mock_astream):
            await self.node._execute_tasks(state, config, "test_tool_call")

            # Check that reasoning messages were written to stream
            write_calls = mock_writer.call_args_list
            reasoning_calls = [
                call
                for call in write_calls
                if any("Planning approach" in str(arg) or "Executing query" in str(arg) for arg in call[0])
            ]
            self.assertGreater(len(reasoning_calls), 0)

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    async def test_task_progress_updates(self, mock_get_stream_writer):
        """Test that task progress updates are properly handled."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        task = self._create_task_execution_item(task_id="task_1")
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        # Mock callback setup
        with patch.object(self.node._execute_tasks_tool, "set_reasoning_callback") as mock_set_reasoning:
            with patch.object(self.node._execute_tasks_tool, "set_task_progress_callback") as mock_set_progress:

                async def mock_astream(input_tuples, config):
                    yield DeepResearchSingleTaskResult(
                        id="task_1",
                        description="Test task",
                        result="Success",
                        artifacts=[],
                        status=TaskExecutionStatus.COMPLETED,
                    )

                with patch.object(self.node._execute_tasks_tool, "astream", side_effect=mock_astream):
                    await self.node._execute_tasks(state, config, "test_tool_call")

                    mock_set_reasoning.assert_called_once()
                    mock_set_progress.assert_called_once()


class TestTaskExecutorNodeStateManagement(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    async def test_task_status_transitions(self, mock_get_stream_writer):
        """Test that task statuses are properly updated during execution."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        task = self._create_task_execution_item(task_id="task_1", status=TaskExecutionStatus.PENDING)
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        async def mock_astream(input_tuples, config):
            yield DeepResearchSingleTaskResult(
                id="task_1",
                description="Test task",
                result="Success",
                artifacts=[self._create_insight_artifact(artifact_id="art_1")],
                status=TaskExecutionStatus.COMPLETED,
            )

        with patch.object(self.node._execute_tasks_tool, "astream", side_effect=mock_astream):
            result = await self.node._execute_tasks(state, config, "test_tool_call")

            # Check task status was updated
            final_message = result.messages[0]
            self.assertIsInstance(final_message, TaskExecutionMessage)
            updated_task = final_message.tasks[0]
            self.assertEqual(updated_task.status, TaskExecutionStatus.COMPLETED)
            self.assertIsNotNone(updated_task.artifact_ids)
            self.assertEqual(updated_task.artifact_ids, ["art_1"])

    @parameterized.expand(
        [
            ["pending"],
            ["in_progress"],
            ["completed"],
            ["failed"],
        ]
    )
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    async def test_artifact_handling_with_different_task_statuses(self, status_str, mock_get_stream_writer):
        """Test artifact handling with different task statuses."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        status = TaskExecutionStatus(status_str)
        task = self._create_task_execution_item(task_id="task_1")
        artifacts = [self._create_insight_artifact(artifact_id="art_1")]
        state = self._create_state_with_tasks(
            tasks=[task],
            task_results=[
                DeepResearchSingleTaskResult(
                    id="prev_task",
                    description="Previous",
                    result="Result",
                    artifacts=artifacts,
                    status=TaskExecutionStatus.COMPLETED,
                )
            ],
        )
        config = RunnableConfig()

        async def mock_astream(input_tuples, config):
            yield DeepResearchSingleTaskResult(
                id="task_1",
                description="Test task",
                result="Result",
                artifacts=artifacts if status == TaskExecutionStatus.COMPLETED else [],
                status=status,
            )

        with patch.object(self.node._execute_tasks_tool, "astream", side_effect=mock_astream):
            result = await self.node._execute_tasks(state, config, "test_tool_call")

            self.assertEqual(len(result.task_results), 1)
            self.assertEqual(result.task_results[0].status, status)
            if status == TaskExecutionStatus.COMPLETED:
                self.assertEqual(len(result.task_results[0].artifacts), 1)
            else:
                self.assertEqual(len(result.task_results[0].artifacts), 0)


class TestTaskExecutorNodeEdgeCases(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    async def test_multiple_tasks_execution(self, mock_get_stream_writer):
        """Test execution with multiple tasks."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        task1 = self._create_task_execution_item(task_id="task_1", description="First task")
        task2 = self._create_task_execution_item(task_id="task_2", description="Second task")
        state = self._create_state_with_tasks(tasks=[task1, task2])
        config = RunnableConfig()

        async def mock_astream(input_tuples, config):
            for i, (task, _) in enumerate(input_tuples):
                yield DeepResearchSingleTaskResult(
                    id=task.id,
                    description=task.description,
                    result=f"Result {i + 1}",
                    artifacts=[],
                    status=TaskExecutionStatus.COMPLETED,
                )

        with patch.object(self.node._execute_tasks_tool, "astream", side_effect=mock_astream):
            result = await self.node._execute_tasks(state, config, "test_tool_call")

            self.assertEqual(len(result.task_results), 2)
            self.assertIn("Result 1", result.messages[1].content)
            self.assertIn("Result 2", result.messages[1].content)

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.get_stream_writer")
    async def test_tasks_with_artifact_dependencies(self, mock_get_stream_writer):
        """Test task execution with artifact dependencies."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        artifact = self._create_insight_artifact(artifact_id="dep_artifact")
        task = self._create_task_execution_item(task_id="task_1", artifact_ids=["dep_artifact"])

        state = self._create_state_with_tasks(
            tasks=[task],
            task_results=[
                DeepResearchSingleTaskResult(
                    id="dep_task",
                    description="Dependency task",
                    result="Dependency result",
                    artifacts=[artifact],
                    status=TaskExecutionStatus.COMPLETED,
                )
            ],
        )
        config = RunnableConfig()

        captured_input_tuples = None

        async def mock_astream(input_tuples, config):
            nonlocal captured_input_tuples
            captured_input_tuples = input_tuples
            yield DeepResearchSingleTaskResult(
                id="task_1",
                description="Test task",
                result="Success",
                artifacts=[],
                status=TaskExecutionStatus.COMPLETED,
            )

        with patch.object(self.node._execute_tasks_tool, "astream", side_effect=mock_astream):
            await self.node._execute_tasks(state, config, "test_tool_call")

            # Check that artifact was passed to the task
            self.assertIsNotNone(captured_input_tuples)
            self.assertEqual(len(captured_input_tuples), 1)
            task_tuple = captured_input_tuples[0]
            self.assertEqual(len(task_tuple[1]), 1)  # One artifact passed
            self.assertEqual(task_tuple[1][0].id, "dep_artifact")

    @parameterized.expand(
        [
            [None, "No tasks"],
            [[], "Empty task list"],
            [[{"invalid": "task"}], "Invalid task format"],
        ]
    )
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.logger")
    async def test_invalid_task_formats(self, invalid_tasks, test_case, mock_logger):
        """Test handling of invalid task formats."""
        state = DeepResearchState(
            messages=[self._create_assistant_message_with_tool_calls()],
            tasks=invalid_tasks,
        )
        config = RunnableConfig()

        if invalid_tasks is None:
            # No tasks should be handled gracefully
            result = await self.node.arun(state, config)
            self.assertIsInstance(result, PartialDeepResearchState)
            self.assertEqual(result.messages[0].content, "No tasks to execute")
        elif invalid_tasks == []:
            # Empty list should be handled gracefully
            result = await self.node.arun(state, config)
            self.assertIsInstance(result, PartialDeepResearchState)
            self.assertEqual(result.messages[0].content, "No tasks to execute")
        else:
            # Invalid task objects would cause validation errors during processing
            with patch.object(self.node, "_execute_tasks") as mock_execute:
                mock_execute.side_effect = ValueError("Invalid task format")
                with self.assertRaises(ValueError):
                    await self.node.arun(state, config)
