import uuid
import asyncio

from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    HumanMessage,
    ReasoningMessage,
    TaskExecutionMessage,
    TaskExecutionStatus,
    VisualizationMessage,
)

from ee.hogai.graph.deep_research.task_executor.nodes import DeepResearchTaskExecutorNode
from ee.hogai.graph.deep_research.types import DeepResearchState, DeepResearchTask, PartialDeepResearchState
from ee.hogai.utils.types.base import AssistantMessageUnion, InsightArtifact, TaskResult


class TestTaskExecutorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_team.name = "Test Team"
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.email = "test@example.com"

        self.node = DeepResearchTaskExecutorNode(self.mock_team, self.mock_user)

    def _create_task_execution_item(
        self,
        task_id: str | None = None,
        description: str = "Test task",
        prompt: str = "Test prompt",
        status: TaskExecutionStatus = TaskExecutionStatus.PENDING,
        artifact_ids: list[str] | None = None,
        progress_text: str | None = None,
    ) -> DeepResearchTask:
        return DeepResearchTask(
            id=task_id or str(uuid.uuid4()),
            description=description,
            prompt=prompt,
            status=status,
            artifact_ids=artifact_ids,
            progress_text=progress_text,
            task_type="create_insight",
        )

    def _create_insight_artifact(
        self,
        artifact_id: str | None = None,
        description: str = "Test artifact",
        query: str = "Test query",
    ) -> InsightArtifact:
        return InsightArtifact(
            task_id=artifact_id or str(uuid.uuid4()),
            id=None,
            content=description,
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
        tasks: list[DeepResearchTask] | None = None,
        messages: list | None = None,
        task_results: list[TaskResult] | None = None,
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
    def test_node_initializes_correctly(self):
        """Test that DeepResearchTaskExecutorNode initializes correctly."""
        self.assertIsNotNone(self.node)
        self.assertEqual(self.node._team, self.mock_team)
        self.assertEqual(self.node._user, self.mock_user)
        self.assertIsNotNone(self.node._task_execution_message_id)


class TestTaskExecutorNodeArun(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    async def test_arun_with_valid_tool_call_and_tasks(self, mock_write_message):
        """Test successful execution with valid tool call message and tasks."""
        task = self._create_task_execution_item()
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        # Mock the insights graph execution
        with patch.object(self.node, "_execute_task_with_insights") as mock_execute:
            mock_execute.return_value = TaskResult(
                id=task.id,
                description=task.description,
                result="Task completed",
                artifacts=[self._create_insight_artifact()],
                status=TaskExecutionStatus.COMPLETED,
            )

            result = await self.node.arun(state, config)

            self.assertIsInstance(result, PartialDeepResearchState)
            self.assertEqual(len(result.messages), 2)
            self.assertIsInstance(result.messages[0], TaskExecutionMessage)
            self.assertIsInstance(result.messages[1], AssistantToolCallMessage)

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
        messages = result.messages
        self.assertEqual(len(messages), 1)
        result_message = messages[0]
        self.assertIsInstance(result_message, AssistantToolCallMessage)
        # Type narrowing for mypy
        assert isinstance(result_message, AssistantToolCallMessage)
        self.assertEqual(result_message.content, "No tasks to execute")
        self.assertEqual(result_message.tool_call_id, "test_tool_call")
        mock_logger.warning.assert_called_once_with("No research step provided to execute")


class TestTaskExecutorInsightsExecution(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.InsightsAssistantGraph")
    async def test_execute_task_with_insights_successful(self, mock_insights_graph_class, mock_write_message):
        """Test successful task execution through insights pipeline."""
        task = self._create_task_execution_item(task_id="task_1")

        # Mock the insights graph
        mock_graph = AsyncMock()
        mock_insights_graph_class.return_value.compile_full_graph.return_value = mock_graph

        # Create a visualization message that will be extracted
        viz_message = VisualizationMessage(
            id="viz_1",
            answer={"kind": "TrendsQuery"},
        )

        # Mock the async stream from insights graph
        async def mock_astream(*args, **kwargs):
            yield {("insights_graph", "viz_node"): {"messages": [viz_message]}}
            yield {
                ("insights_graph", "final"): {
                    "messages": [
                        AssistantToolCallMessage(
                            content="Insights generated successfully", tool_call_id="task_tool_call_id"
                        )
                    ]
                }
            }

        mock_graph.astream = mock_astream
        mock_graph.aget_reasoning_message_by_node_name = {
            "viz_node": lambda *args: ReasoningMessage(content="Processing")
        }

        # Execute the task
        input_dict = {"task_id": task.id, "task": task, "artifacts": [], "config": RunnableConfig()}

        result = await self.node._execute_create_insight(input_dict)

        self.assertIsInstance(result, TaskResult)
        self.assertIsNotNone(result)  # Ensure result is not None for mypy
        assert result is not None  # Type narrowing for mypy
        self.assertEqual(result.id, task.id)
        self.assertEqual(result.status, TaskExecutionStatus.COMPLETED)
        self.assertEqual(len(result.artifacts), 1)

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.InsightsAssistantGraph")
    async def test_execute_task_with_insights_no_artifacts(self, mock_insights_graph_class, mock_write_message):
        """Test task execution that produces no artifacts."""
        task = self._create_task_execution_item(task_id="task_1")

        # Mock the insights graph
        mock_graph = AsyncMock()
        mock_insights_graph_class.return_value.compile_full_graph.return_value = mock_graph

        # Mock stream with no visualization messages
        async def mock_astream(*args, **kwargs):
            yield {
                ("insights_graph", "final"): {
                    "messages": [
                        AssistantToolCallMessage(
                            content="No insights could be generated", tool_call_id="task_tool_call_id"
                        )
                    ]
                }
            }

        mock_graph.astream = mock_astream
        mock_graph.aget_reasoning_message_by_node_name = {}

        # Execute the task
        input_dict = {"task_id": task.id, "task": task, "artifacts": [], "config": RunnableConfig()}

        result = await self.node._execute_create_insight(input_dict)

        self.assertIsInstance(result, TaskResult)
        self.assertIsNotNone(result)  # Ensure result is not None for mypy
        assert result is not None  # Type narrowing for mypy
        self.assertEqual(result.id, task.id)
        self.assertEqual(result.status, TaskExecutionStatus.FAILED)
        self.assertEqual(len(result.artifacts), 0)

    @patch("ee.hogai.graph.deep_research.task_executor.nodes.capture_exception")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.InsightsAssistantGraph")
    async def test_execute_task_with_exception(self, mock_insights_graph_class, mock_write_message, mock_capture):
        """Test task execution that encounters an exception."""
        task = self._create_task_execution_item(task_id="task_1")

        # Mock the insights graph to raise an exception
        mock_graph = AsyncMock()
        mock_insights_graph_class.return_value.compile_full_graph.return_value = mock_graph

        test_exception = Exception("Insights generation failed")

        async def mock_astream(*args, **kwargs):
            raise test_exception

        mock_graph.astream = mock_astream

        # Execute the task
        input_dict = {"task_id": task.id, "task": task, "artifacts": [], "config": RunnableConfig()}

        with self.assertRaises(Exception) as cm:
            await self.node._execute_create_insight(input_dict)

        self.assertEqual(str(cm.exception), "Insights generation failed")
        mock_capture.assert_called_once_with(test_exception)


class TestParallelTaskExecution(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    async def test_multiple_tasks_executed_in_parallel(self, mock_write_message):
        """Test that multiple tasks are executed in parallel."""
        task1 = self._create_task_execution_item(task_id="task_1")
        task2 = self._create_task_execution_item(task_id="task_2")
        task3 = self._create_task_execution_item(task_id="task_3")

        state = self._create_state_with_tasks(tasks=[task1, task2, task3])
        config = RunnableConfig()

        execution_order = []

        async def mock_execute_task1(input_dict):
            await asyncio.sleep(0.1)
            execution_order.append("task_1")
            return TaskResult(
                id="task_1", description="Task 1", result="Result 1", artifacts=[], status=TaskExecutionStatus.COMPLETED
            )

        async def mock_execute_task2(input_dict):
            await asyncio.sleep(0.05)
            execution_order.append("task_2")
            return TaskResult(
                id="task_2", description="Task 2", result="Result 2", artifacts=[], status=TaskExecutionStatus.COMPLETED
            )

        async def mock_execute_task3(input_dict):
            execution_order.append("task_3")
            return TaskResult(
                id="task_3", description="Task 3", result="Result 3", artifacts=[], status=TaskExecutionStatus.COMPLETED
            )

        with patch.object(self.node, "_execute_task_with_insights") as mock_execute:
            mock_execute.side_effect = [mock_execute_task3, mock_execute_task2, mock_execute_task1]

            result = await self.node.arun(state, config)

            # Tasks should complete in order of execution time
            self.assertEqual(execution_order, ["task_3", "task_2", "task_1"])

            # Check final state
            self.assertIsInstance(result, PartialDeepResearchState)
            self.assertEqual(len(result.task_results), 3)
            self.assertIsNone(result.tasks)


class TestReasoningCallback(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.InsightsAssistantGraph")
    async def test_reasoning_messages_sent_during_execution(self, mock_insights_graph_class, mock_write_message):
        """Test that reasoning messages are properly sent during task execution."""
        task = self._create_task_execution_item(task_id="task_1")
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        # Mock the insights graph
        mock_graph = AsyncMock()
        mock_insights_graph_class.return_value.compile_full_graph.return_value = mock_graph

        # Create reasoning message function
        async def get_reasoning_message(input_data, default):
            return ReasoningMessage(
                content="Analyzing data patterns", substeps=["Loading data", "Running analysis", "Generating insights"]
            )

        mock_graph.aget_reasoning_message_by_node_name = {"analysis_node": get_reasoning_message}

        async def mock_astream(*args, **kwargs):
            # Yield task started update
            yield {"__pregel_task_id": "task_123", "payload": {"name": "analysis_node", "input": {"data": "test"}}}
            # Yield final result
            yield {
                ("insights_graph", "final"): {
                    "messages": [
                        VisualizationMessage(id="viz_1", answer={"kind": "TrendsQuery"}),
                        AssistantToolCallMessage(content="Analysis complete", tool_call_id="task_tool_call"),
                    ]
                }
            }

        mock_graph.astream = mock_astream

        await self.node.arun(state, config)

        # Verify reasoning callback was triggered
        reasoning_calls = [
            call
            for call in mock_write_message.call_args_list
            if len(call[0]) > 0 and isinstance(call[0][0], ReasoningMessage)
        ]
        # For single task, reasoning messages should be sent
        self.assertGreater(len(reasoning_calls), 0)


class TestStateManagement(TestTaskExecutorNode):
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    async def test_task_status_transitions(self, mock_write_message):
        """Test that task statuses are properly updated during execution."""
        task = self._create_task_execution_item(task_id="task_1", status=TaskExecutionStatus.PENDING)
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        with patch.object(self.node, "_execute_task_with_insights") as mock_execute:
            mock_execute.return_value = TaskResult(
                id="task_1",
                description="Test task",
                result="Success",
                artifacts=[self._create_insight_artifact(artifact_id="art_1")],
                status=TaskExecutionStatus.COMPLETED,
            )

            result = await self.node.arun(state, config)

            # Check task status was updated in the message
            final_message = result.messages[0]
            self.assertIsInstance(final_message, TaskExecutionMessage)
            # Type narrowing for mypy
            assert isinstance(final_message, TaskExecutionMessage)
            updated_task = final_message.tasks[0]
            self.assertEqual(updated_task.status, TaskExecutionStatus.COMPLETED)
            self.assertIsNotNone(updated_task.artifact_ids)
            self.assertEqual(updated_task.artifact_ids, ["art_1"])

    @parameterized.expand(
        [
            ["completed", TaskExecutionStatus.COMPLETED],
            ["failed", TaskExecutionStatus.FAILED],
        ]
    )
    @patch("ee.hogai.graph.deep_research.task_executor.nodes.DeepResearchTaskExecutorNode._write_message")
    async def test_different_task_completion_statuses(self, status_str, status, mock_write_message):
        """Test handling of different task completion statuses."""
        task = self._create_task_execution_item(task_id="task_1")
        state = self._create_state_with_tasks(tasks=[task])
        config = RunnableConfig()

        artifacts = [self._create_insight_artifact()] if status == TaskExecutionStatus.COMPLETED else []

        with patch.object(self.node, "_execute_task_with_insights") as mock_execute:
            mock_execute.return_value = TaskResult(
                id="task_1", description="Test task", result="Result", artifacts=artifacts, status=status
            )

            result = await self.node.arun(state, config)

            self.assertEqual(len(result.task_results), 1)
            self.assertEqual(result.task_results[0].status, status)
            if status == TaskExecutionStatus.COMPLETED:
                self.assertEqual(len(result.task_results[0].artifacts), 1)
            else:
                self.assertEqual(len(result.task_results[0].artifacts), 0)


class TestArtifactExtraction(TestTaskExecutorNode):
    def test_extract_artifacts_from_visualization_messages(self):
        """Test artifact extraction from visualization messages."""
        task = self._create_task_execution_item(task_id="task_1", prompt="Generate trends analysis")

        viz_message = VisualizationMessage(id="viz_1", answer={"kind": "TrendsQuery", "series": []})

        messages: list[AssistantMessageUnion] = [
            ReasoningMessage(content="Planning analysis"),
            viz_message,
            AssistantToolCallMessage(content="Complete", tool_call_id="test"),
        ]

        artifacts = self.node._extract_artifacts(messages, task)

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].task_id, "task_1")
        self.assertEqual(artifacts[0].content, "Generate trends analysis")
        self.assertEqual(artifacts[0].query.kind, "TrendsQuery")

    def test_extract_artifacts_handles_no_visualizations(self):
        """Test artifact extraction when no visualization messages exist."""
        task = self._create_task_execution_item(task_id="task_1")

        messages: list[AssistantMessageUnion] = [
            ReasoningMessage(content="Planning analysis"),
            AssistantToolCallMessage(content="No data available", tool_call_id="test"),
        ]

        artifacts = self.node._extract_artifacts(messages, task)

        self.assertEqual(len(artifacts), 0)
