import uuid
import asyncio
from typing import Any

from unittest import TestCase
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig
from pydantic import ConfigDict

from posthog.schema import ReasoningMessage, TaskExecutionItem, TaskExecutionMessage, TaskExecutionStatus

from ee.hogai.graph.deep_research.types import DeepResearchNodeName
from ee.hogai.graph.parallel_task_execution.nodes import BaseTaskExecutorNode, TaskExecutionInputTuple
from ee.hogai.utils.types.base import BaseStateWithTasks, TaskArtifact, TaskResult
from ee.hogai.utils.types.composed import MaxNodeName


class MockTestState(BaseStateWithTasks):
    """Mock state for testing the base class."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    test_input_tuples: list[TaskExecutionInputTuple] = []


class MockPartialTestState(BaseStateWithTasks):
    """Mock partial test state for testing the base class."""

    pass


class TaskExecutorNodeImplementation(BaseTaskExecutorNode[MockTestState, MockPartialTestState]):
    """Concrete implementation for testing the base class."""

    def __init__(self, team, user):
        super().__init__(team, user)
        self.input_tuples_called = False
        self.final_state_called = False

    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.TASK_EXECUTOR

    async def arun(self, state: MockTestState, config: RunnableConfig) -> MockPartialTestState:
        """Forward to the base _arun method."""
        return await self._arun(state, config)

    async def _aget_input_tuples(self, state: MockTestState) -> list[TaskExecutionInputTuple]:
        self.input_tuples_called = True
        # Return test input tuples based on state
        return getattr(state, "test_input_tuples", [])

    async def _aget_final_state(
        self, tasks: list[TaskExecutionItem], task_results: list[TaskResult]
    ) -> MockPartialTestState:
        self.final_state_called = True
        return MockPartialTestState(messages=[])


class TestBaseTaskExecutorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.node = TaskExecutorNodeImplementation(self.mock_team, self.mock_user)

    def _create_task(self, task_id: str | None = None, description: str = "Test task") -> TaskExecutionItem:
        return TaskExecutionItem(
            id=task_id or str(uuid.uuid4()),
            description=description,
            prompt="Test prompt",
            status=TaskExecutionStatus.PENDING,
            task_type="create_insight",  # Added required field
        )

    def _create_task_result(
        self, task_id: str, status: TaskExecutionStatus = TaskExecutionStatus.COMPLETED
    ) -> TaskResult:
        return TaskResult(
            id=task_id,
            description="Test result",
            result="Success",
            artifacts=[],
            status=status,
        )


class TestTaskExecution(TestBaseTaskExecutorNode):
    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_single_task_execution(self, mock_write_message):
        """Test execution of a single task."""
        task = self._create_task("task1")

        async def task_coroutine(_: Any):
            return self._create_task_result("task1")

        state = MockTestState(messages=[])
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        self.assertTrue(self.node.input_tuples_called)
        self.assertTrue(self.node.final_state_called)
        # Should not send task execution message for single task
        task_execution_calls = [
            call for call in mock_write_message.call_args_list if isinstance(call[0][0], TaskExecutionMessage)
        ]
        self.assertEqual(len(task_execution_calls), 0)

    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_multiple_tasks_parallel_execution(self, mock_write_message):
        """Test that multiple tasks are executed in parallel."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")
        task3 = self._create_task("task3")

        execution_order = []

        async def task1_coroutine(input_dict):
            await asyncio.sleep(0.1)
            execution_order.append("task1")
            return self._create_task_result("task1")

        async def task2_coroutine(input_dict):
            await asyncio.sleep(0.05)
            execution_order.append("task2")
            return self._create_task_result("task2")

        async def task3_coroutine(input_dict):
            execution_order.append("task3")
            return self._create_task_result("task3")

        state = MockTestState(messages=[])
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
            (task3, [], task3_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Tasks should complete in order of their execution time, not submission
        self.assertEqual(execution_order, ["task3", "task2", "task1"])

        # Should send task execution messages for multiple tasks
        task_execution_calls = [
            call for call in mock_write_message.call_args_list if isinstance(call[0][0], TaskExecutionMessage)
        ]
        self.assertGreater(len(task_execution_calls), 0)

    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_task_status_transitions(self, mock_write_message):
        """Test that task statuses are properly updated during execution."""
        task = self._create_task("task1")

        async def task_coroutine(_: Any):
            return self._create_task_result("task1")

        state = MockTestState(messages=[])
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Task should start as IN_PROGRESS
        self.assertEqual(task.status, TaskExecutionStatus.COMPLETED)


class TestReasoningCallback(TestBaseTaskExecutorNode):
    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_reasoning_callback_for_single_task(self, mock_write_message):
        """Test that reasoning messages are sent for single task execution."""
        task = self._create_task("task1")

        async def task_coroutine(input_dict):
            # Simulate sending reasoning messages
            await self.node._reasoning_callback("task1", "Starting analysis")
            await self.node._reasoning_callback("task1", "Processing data")
            return self._create_task_result("task1")

        state = MockTestState(messages=[])
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Should send reasoning messages for single task
        reasoning_calls = [
            call for call in mock_write_message.call_args_list if isinstance(call[0][0], ReasoningMessage)
        ]
        self.assertEqual(len(reasoning_calls), 2)
        self.assertEqual(reasoning_calls[0][0][0].content, "Starting analysis")
        self.assertEqual(reasoning_calls[1][0][0].content, "Processing data")

    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_reasoning_callback_for_multiple_tasks(self, mock_write_message):
        """Test that task execution messages are updated for multiple tasks."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        async def task1_coroutine(input_dict):
            await self.node._reasoning_callback("task1", "Task 1 progress")
            return self._create_task_result("task1")

        async def task2_coroutine(input_dict):
            await self.node._reasoning_callback("task2", "Task 2 progress")
            return self._create_task_result("task2")

        state = MockTestState(messages=[])
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Should update task execution messages for multiple tasks
        task_execution_calls = [
            call for call in mock_write_message.call_args_list if isinstance(call[0][0], TaskExecutionMessage)
        ]
        self.assertGreater(len(task_execution_calls), 0)

        # No reasoning messages should be sent for multiple tasks
        reasoning_calls = [
            call for call in mock_write_message.call_args_list if isinstance(call[0][0], ReasoningMessage)
        ]
        self.assertEqual(len(reasoning_calls), 0)


class TestErrorHandling(TestBaseTaskExecutorNode):
    @patch("ee.hogai.graph.parallel_task_execution.nodes.capture_exception")
    async def test_handles_task_failure(self, mock_capture):
        """Test that individual task failures are handled gracefully."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        async def task1_coroutine(input_dict):
            raise ValueError("Task 1 failed")

        async def task2_coroutine(input_dict):
            return self._create_task_result("task2")

        state = MockTestState(messages=[])
        state.test_input_tuples = [
            (task1, [], task1_coroutine),
            (task2, [], task2_coroutine),
        ]
        config = RunnableConfig()

        # Task 2 should still complete even if task 1 fails
        await self.node.arun(state, config)
        self.assertTrue(self.node.final_state_called)

    @patch("ee.hogai.graph.parallel_task_execution.nodes.capture_exception")
    async def test_handles_general_exception(self, mock_capture):
        """Test that general exceptions are captured and re-raised."""
        # Mock _aget_input_tuples to raise an exception
        with patch.object(self.node, "_aget_input_tuples") as mock_get_input:
            mock_get_input.side_effect = RuntimeError("General failure")

            state = MockTestState(messages=[])
            config = RunnableConfig()

            with self.assertRaises(RuntimeError):
                await self.node.arun(state, config)

            mock_capture.assert_called_once()

    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_cancels_remaining_tasks_on_exception(self, mock_write_message):
        """Test that remaining tasks are cancelled when an exception occurs."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        task2_started = asyncio.Event()
        task2_cancelled = False

        async def task1_coroutine(input_dict):
            await task2_started.wait()  # Wait for task2 to start
            raise RuntimeError("Critical failure")

        async def task2_coroutine(input_dict):
            nonlocal task2_cancelled
            task2_started.set()
            try:
                await asyncio.sleep(10)  # Long running task
                return self._create_task_result("task2")
            except asyncio.CancelledError:
                task2_cancelled = True
                raise

        # Mock _aget_final_state to raise an exception
        with patch.object(self.node, "_aget_final_state") as mock_final_state:
            mock_final_state.side_effect = RuntimeError("Critical failure in final state")

            state = MockTestState(messages=[])
            state.test_input_tuples = [
                (task1, [], task1_coroutine),
                (task2, [], task2_coroutine),
            ]
            config = RunnableConfig()

            with self.assertRaises(RuntimeError):
                await self.node.arun(state, config)


class TestArtifactHandling(TestBaseTaskExecutorNode):
    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_artifacts_update_task_items(self, mock_write_message):
        """Test that artifacts are properly added to task items."""
        task = self._create_task("task1")

        artifact = TaskArtifact(id=None, task_id="artifact1", content="Test artifact")

        async def task_coroutine(input_dict):
            result = self._create_task_result("task1")
            result.artifacts = [artifact]
            return result

        state = MockTestState(messages=[])
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Task should have artifact IDs updated
        self.assertEqual(task.artifact_ids, ["artifact1"])

    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_passes_artifacts_to_coroutines(self, mock_write_message):
        """Test that artifacts are passed correctly to task coroutines."""
        task = self._create_task("task1")
        input_artifact = TaskArtifact(id=None, task_id="input_artifact", content="Input artifact")

        received_artifacts = None

        async def task_coroutine(input_dict):
            nonlocal received_artifacts
            received_artifacts = input_dict.get("artifacts")
            return self._create_task_result("task1")

        state = MockTestState()
        state.test_input_tuples = [(task, [input_artifact], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        self.assertEqual(received_artifacts, [input_artifact])


class TestMessageFlow(TestBaseTaskExecutorNode):
    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_no_task_execution_message_for_single_task(self, mock_write_message):
        """Test that no TaskExecutionMessage is sent for single task."""
        task = self._create_task("task1")

        async def task_coroutine(_: Any):
            return self._create_task_result("task1")

        state = MockTestState()
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        task_execution_calls = [
            call for call in mock_write_message.call_args_list if isinstance(call[0][0], TaskExecutionMessage)
        ]
        self.assertEqual(len(task_execution_calls), 0)

    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_task_execution_messages_for_multiple_tasks(self, mock_write_message):
        """Test that TaskExecutionMessages are sent for multiple tasks."""
        task1 = self._create_task("task1")
        task2 = self._create_task("task2")

        async def task_coroutine(input_dict):
            task_id = input_dict["task"].id
            return self._create_task_result(task_id)

        state = MockTestState()
        state.test_input_tuples = [
            (task1, [], task_coroutine),
            (task2, [], task_coroutine),
        ]
        config = RunnableConfig()

        await self.node.arun(state, config)

        task_execution_calls = [
            call for call in mock_write_message.call_args_list if isinstance(call[0][0], TaskExecutionMessage)
        ]
        # Should send initial, update, and final messages
        self.assertGreaterEqual(len(task_execution_calls), 3)

        # All messages should have the same ID
        message_ids = {call[0][0].id for call in task_execution_calls}
        self.assertEqual(len(message_ids), 1)
        self.assertEqual(message_ids.pop(), self.node._task_execution_message_id)


class TestEdgeCases(TestBaseTaskExecutorNode):
    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_empty_input_tuples_raises_error(self, mock_write_message):
        """Test that empty input tuples raises ValueError."""
        state = MockTestState()
        state.test_input_tuples = []
        config = RunnableConfig()

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, config)

        self.assertEqual(str(cm.exception), "No input tuples provided")
        self.assertTrue(self.node.input_tuples_called)
        self.assertFalse(self.node.final_state_called)  # Should not reach final state

    @patch("ee.hogai.graph.parallel_task_execution.nodes.BaseTaskExecutorNode._write_message")
    async def test_none_task_result(self, mock_write_message):
        """Test handling of None task results."""
        task = self._create_task("task1")

        async def task_coroutine(input_dict):
            return None  # Return None instead of TaskResult

        state = MockTestState()
        state.test_input_tuples = [(task, [], task_coroutine)]
        config = RunnableConfig()

        await self.node.arun(state, config)

        # Should handle None gracefully
        self.assertTrue(self.node.final_state_called)
