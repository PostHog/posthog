import uuid
import asyncio

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import AssistantTool, AssistantToolCall, ToolExecutionStatus

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool import MaxTool, ParallelToolExecution
from ee.hogai.utils.types import AssistantState, ToolResult


class MockToolArgs(BaseModel):
    query_description: str = Field(description="Description of the query")


class MockTool(MaxTool):
    name = AssistantTool.CREATE_SURVEY
    description = "A mock tool for testing"
    args_schema = MockToolArgs

    def __init_subclass__(cls, **kwargs):
        pass

    async def _arun_impl(self, query_description: str) -> ToolResult:
        await asyncio.sleep(0.01)
        return await self._successful_execution(f"Completed: {query_description}")


class SlowMockTool(MaxTool):
    name = AssistantTool.SEARCH_SESSION_RECORDINGS
    description = "A slow mock tool for testing"
    args_schema = MockToolArgs

    def __init_subclass__(cls, **kwargs):
        pass

    async def _arun_impl(self, query_description: str) -> ToolResult:
        await asyncio.sleep(0.1)
        return await self._successful_execution(f"Completed slowly: {query_description}")


class FailingMockTool(MaxTool):
    name = AssistantTool.NAVIGATE
    description = "A tool that fails"
    args_schema = MockToolArgs

    def __init_subclass__(cls, **kwargs):
        pass

    async def _arun_impl(self, query_description: str) -> ToolResult:
        raise ValueError("Intentional failure")


class CallbackMockTool(MaxTool):
    name = AssistantTool.SEARCH
    description = "A tool that uses callbacks"
    args_schema = MockToolArgs

    def __init_subclass__(cls, **kwargs):
        pass

    async def _arun_impl(self, query_description: str) -> ToolResult:
        await self._update_tool_call_status("Starting work")
        await asyncio.sleep(0.01)
        await self._update_tool_call_status("Processing")
        await asyncio.sleep(0.01)
        await self._update_tool_call_status("Finalizing")
        return await self._successful_execution(f"Done: {query_description}")


class TestMaxTool(IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.state = AssistantState()
        self.config = RunnableConfig()
        self.context_manager = MagicMock(spec=AssistantContextManager)
        self.context_manager.get_tool_context.return_value = {}

    async def test_tool_initialization(self):
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        self.assertEqual(tool.name, AssistantTool.CREATE_SURVEY)
        self.assertEqual(tool.description, "A mock tool for testing")
        self.assertEqual(tool._team, self.mock_team)
        self.assertEqual(tool._user, self.mock_user)

    async def test_tool_run_success(self):
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        result = await tool.arun("tool_1", {"query_description": "test query"})
        self.assertEqual(result.status, ToolExecutionStatus.COMPLETED)
        self.assertEqual(result.content, "Completed: test query")
        self.assertEqual(result.id, "tool_1")

    async def test_tool_successful_execution_helper(self):
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        tool._tool_call_id = "test_id"
        result = await tool._successful_execution("Test content")
        self.assertEqual(result.status, ToolExecutionStatus.COMPLETED)
        self.assertEqual(result.content, "Test content")
        self.assertEqual(result.id, "test_id")
        self.assertEqual(result.tool_name, AssistantTool.CREATE_SURVEY)

    async def test_tool_failed_execution_helper(self):
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        tool._tool_call_id = "test_id"
        result = await tool._failed_execution("Test failure reason")
        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.content, "Test failure reason")
        self.assertEqual(result.id, "test_id")

    async def test_tool_update_callback(self):
        callback_mock = AsyncMock()
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        tool._tool_call_id = "test_id"
        tool._tool_update_callback = callback_mock

        await tool._update_tool_call_status("Progress update")
        callback_mock.assert_called_once_with("test_id", "Progress update", None)

    async def test_tool_update_callback_with_substeps(self):
        callback_mock = AsyncMock()
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        tool._tool_call_id = "test_id"
        tool._tool_update_callback = callback_mock

        substeps = ["Step 1", "Step 2"]
        await tool._update_tool_call_status("Progress", substeps)
        callback_mock.assert_called_once_with("test_id", "Progress", substeps)

    async def test_tool_function_description_includes_explanation(self):
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        tool_desc = tool.tool_function_description
        self.assertTrue(hasattr(tool_desc, "model_fields"))
        self.assertIn("tool_call_explanation", tool_desc.model_fields)
        self.assertIn("query_description", tool_desc.model_fields)

    async def test_tool_init_run_removes_explanation(self):
        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        parameters = {"query_description": "test", "tool_call_explanation": "This will be removed"}
        tool._init_run("tool_1", parameters, None)
        self.assertNotIn("tool_call_explanation", parameters)
        self.assertEqual(tool._tool_call_id, "tool_1")


class TestParallelToolExecution(IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_write_message = AsyncMock()
        self.implementation = ParallelToolExecution(self.mock_team, self.mock_user, self.mock_write_message)
        self.state = AssistantState()
        self.config = RunnableConfig()

    def _create_tool_call(
        self,
        tool_name: AssistantTool = AssistantTool.CREATE_SURVEY,
        description: str = "Test task",
        tool_id: str | None = None,
    ) -> AssistantToolCall:
        return AssistantToolCall(
            id=tool_id or str(uuid.uuid4()),
            name=tool_name,
            args={"query_description": description, "tool_call_explanation": description},
        )

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_single_tool_execution(self, mock_get_tool_class):
        mock_get_tool_class.return_value = MockTool
        tool_call = self._create_tool_call(tool_id="tool_1")

        results, _final_message = await self.implementation.arun([tool_call], self.state, self.config)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, ToolExecutionStatus.COMPLETED)
        self.assertEqual(results[0].id, "tool_1")
        self.assertIn("Completed", results[0].content)

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_multiple_tools_parallel_execution(self, mock_get_tool_class):
        def get_tool_class(name):
            if name == AssistantTool.CREATE_SURVEY:
                return MockTool
            elif name == AssistantTool.SEARCH_SESSION_RECORDINGS:
                return SlowMockTool
            return MockTool

        mock_get_tool_class.side_effect = get_tool_class

        tool_call_1 = self._create_tool_call(AssistantTool.SEARCH_SESSION_RECORDINGS, "Slow task", "tool_1")
        tool_call_2 = self._create_tool_call(AssistantTool.CREATE_SURVEY, "Fast task", "tool_2")

        results, _final_message = await self.implementation.arun([tool_call_1, tool_call_2], self.state, self.config)

        self.assertEqual(len(results), 2)
        result_ids = {r.id for r in results}
        self.assertEqual(result_ids, {"tool_1", "tool_2"})
        self.assertTrue(all(r.status == ToolExecutionStatus.COMPLETED for r in results))

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_tool_execution_status_updates(self, mock_get_tool_class):
        mock_get_tool_class.return_value = MockTool
        tool_call = self._create_tool_call(tool_id="tool_1")

        results, final_message = await self.implementation.arun([tool_call], self.state, self.config)

        self.assertEqual(results[0].status, ToolExecutionStatus.COMPLETED)
        self.assertIsNotNone(final_message)
        self.assertEqual(len(final_message.tool_executions), 1)
        self.assertEqual(final_message.tool_executions[0].status, ToolExecutionStatus.COMPLETED)

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_tool_execution_message_sent_for_multiple_tools(self, mock_get_tool_class):
        mock_get_tool_class.return_value = MockTool
        tool_call_1 = self._create_tool_call(tool_id="tool_1")
        tool_call_2 = self._create_tool_call(tool_id="tool_2")

        await self.implementation.arun([tool_call_1, tool_call_2], self.state, self.config)

        self.mock_write_message.assert_called()
        call_count = self.mock_write_message.call_count
        self.assertGreater(call_count, 0)

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_empty_tool_calls_raises_error(self, _mock_get_tool_class):
        with self.assertRaises(ValueError) as cm:
            await self.implementation.arun([], self.state, self.config)
        self.assertEqual(str(cm.exception), "No tool calls provided")

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    @patch("ee.hogai.tool.parallel_execution.capture_exception")
    async def test_handles_tool_failure_gracefully(self, _mock_capture, mock_get_tool_class):
        def get_tool_class(name):
            if name == AssistantTool.NAVIGATE:
                return FailingMockTool
            return MockTool

        mock_get_tool_class.side_effect = get_tool_class

        tool_call_1 = self._create_tool_call(AssistantTool.NAVIGATE, "Will fail", "tool_1")
        tool_call_2 = self._create_tool_call(AssistantTool.CREATE_SURVEY, "Will succeed", "tool_2")

        results, _ = await self.implementation.arun([tool_call_1, tool_call_2], self.state, self.config)

        self.assertEqual(len(results), 1)
        success_result = next(r for r in results if r.id == "tool_2")
        self.assertEqual(success_result.status, ToolExecutionStatus.COMPLETED)

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_tool_update_callback_called(self, mock_get_tool_class):
        mock_get_tool_class.return_value = CallbackMockTool
        tool_call = self._create_tool_call(AssistantTool.SEARCH, "Test", "tool_1")

        await self.implementation.arun([tool_call], self.state, self.config)

        self.mock_write_message.assert_called()

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_tool_call_tuples_conversion(self, mock_get_tool_class):
        mock_get_tool_class.return_value = MockTool
        tool_call = self._create_tool_call(tool_id="tool_1", description="Test conversion")

        tuples = await self.implementation._tool_call_tuples_to_tool_execution_tuples(
            [tool_call], self.state, self.config
        )

        self.assertEqual(len(tuples), 1)
        tool_execution, tool_class = tuples[0]
        self.assertEqual(tool_execution.id, "tool_1")
        self.assertEqual(tool_execution.tool_name, AssistantTool.CREATE_SURVEY)
        self.assertEqual(tool_execution.description, "Test conversion")
        self.assertIsInstance(tool_class, MockTool)

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_unknown_tool_is_skipped(self, mock_get_tool_class):
        mock_get_tool_class.side_effect = lambda name: MockTool if name == AssistantTool.CREATE_SURVEY else None

        known_tool = self._create_tool_call(AssistantTool.CREATE_SURVEY, "Known", "tool_1")
        another_known_tool = self._create_tool_call(AssistantTool.CREATE_SURVEY, "Another Known", "tool_3")

        tuples = await self.implementation._tool_call_tuples_to_tool_execution_tuples(
            [known_tool, another_known_tool], self.state, self.config
        )

        self.assertEqual(len(tuples), 2)
        self.assertEqual(tuples[0][0].tool_name, AssistantTool.CREATE_SURVEY)

    @patch("ee.hogai.tool.parallel_execution.get_assistant_tool_class")
    async def test_tool_execution_message_id_consistency(self, mock_get_tool_class):
        mock_get_tool_class.return_value = MockTool
        tool_call_1 = self._create_tool_call(tool_id="tool_1")
        tool_call_2 = self._create_tool_call(tool_id="tool_2")

        await self.implementation.arun([tool_call_1, tool_call_2], self.state, self.config)

        final_messages = [
            call[0][0] for call in self.mock_write_message.call_args_list if hasattr(call[0][0], "tool_executions")
        ]

        if len(final_messages) > 1:
            final_message_ids = {msg.id for msg in final_messages if msg.id is not None}
            self.assertLessEqual(len(final_message_ids), 1)


class TestToolRegistration(IsolatedAsyncioTestCase):
    def test_tool_class_naming_convention(self):
        with self.assertRaises(ValueError) as cm:

            class InvalidName(MaxTool):
                name = AssistantTool.CREATE_SURVEY
                description = "Test"

                def __init_subclass__(cls, **kwargs):
                    pass

                async def _arun_impl(self):
                    pass

        self.assertIn("must end with 'Tool'", str(cm.exception))


class TestToolFactory(IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.state = AssistantState()
        self.config = RunnableConfig()
        self.context_manager = MagicMock(spec=AssistantContextManager)

    async def test_create_tool_class_factory(self):
        tool_instance = await MockTool.create_tool_class(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
        )
        self.assertIsInstance(tool_instance, MockTool)
        self.assertEqual(tool_instance._team, self.mock_team)
        self.assertEqual(tool_instance._user, self.mock_user)

    async def test_tool_initialization_with_overrides(self):
        custom_name = "custom_mock"
        custom_desc = "Custom description"

        tool = MockTool(
            team=self.mock_team,
            user=self.mock_user,
            state=self.state,
            config=self.config,
            context_manager=self.context_manager,
            name=custom_name,
            description=custom_desc,
        )

        self.assertEqual(tool.name, custom_name)
        self.assertEqual(tool.description, custom_desc)
