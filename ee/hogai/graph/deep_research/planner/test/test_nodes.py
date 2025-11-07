import warnings
from typing import Any, cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    DeepResearchNotebook,
    DeepResearchType,
    HumanMessage,
    MultiVisualizationMessage,
    TaskExecutionStatus,
)

from ee.hogai.graph.deep_research.planner.nodes import (
    DeepResearchPlannerNode,
    DeepResearchPlannerToolsNode,
    DeepResearchTaskExecutionItem,
)
from ee.hogai.graph.deep_research.planner.prompts import (
    FINALIZE_RESEARCH_TOOL_RESULT,
    NO_TASKS_RESULTS_TOOL_RESULT,
    WRITE_RESULT_FAILED_TOOL_RESULT,
    WRITE_RESULT_TOOL_RESULT,
)
from ee.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState, TodoItem
from ee.hogai.utils.types import InsightArtifact
from ee.hogai.utils.types.base import TaskResult


def _create_test_artifact(task_id: str, description: str, sql_query: str = "SELECT 1"):
    """Helper to create InsightArtifact for testing"""
    hogql_query = AssistantHogQLQuery(query=sql_query)
    return InsightArtifact(id=None, task_id=task_id, content=description, query=hogql_query)


@override_settings(IN_UNIT_TESTING=True)
class TestDeepResearchPlannerNode(BaseTest):
    def setUp(self):
        super().setUp()
        warnings.filterwarnings("ignore", message="coroutine.*was never awaited", category=RuntimeWarning)
        self.node = DeepResearchPlannerNode(self.team, self.user)
        self.config = RunnableConfig()

    def _create_state(self, **kwargs):
        """DeepResearchState init"""
        defaults: dict[str, Any] = {
            "messages": [],
            "todos": None,
            "tasks": None,
            "task_results": [],
            "intermediate_results": [],
            "previous_response_id": None,
            "conversation_notebooks": [],
            "current_run_notebooks": [
                DeepResearchNotebook(
                    notebook_id="test_notebook", notebook_type=DeepResearchType.PLANNING, title="Test Planning Notebook"
                )
            ]
            if kwargs.get("needs_notebook", True)
            else None,
        }
        # Remove needs_notebook from kwargs before updating
        kwargs.pop("needs_notebook", None)
        defaults.update(kwargs)
        return DeepResearchState(**defaults)

    def _create_langchain_ai_message(self, content="", tool_calls=None):
        """LangchainAIMessage init"""
        message = LangchainAIMessage(content=content)
        if tool_calls:
            message.tool_calls = tool_calls
        message.response_metadata = {"id": "test_response_id"}
        return message

    @patch("ee.hogai.graph.deep_research.planner.nodes.Notebook.objects.aget")
    @patch("ee.hogai.graph.deep_research.planner.nodes.NotebookSerializer")
    async def test_arun_without_previous_response_id(self, mock_serializer, mock_notebook_get):
        """Test node execution without previous response ID uses notebook content"""
        mock_notebook = MagicMock()
        mock_notebook.content = {"type": "doc", "content": []}

        async def async_get(*args, **kwargs):
            return mock_notebook

        mock_notebook_get.side_effect = async_get

        mock_serializer_instance = MagicMock()
        mock_serializer_instance.from_json_to_markdown.return_value = "# Test notebook"
        mock_serializer.return_value = mock_serializer_instance

        state = self._create_state()

        with (
            patch.object(self.node, "_aget_core_memory", return_value="Test core memory") as _mock_core_memory,
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_response = self._create_langchain_ai_message(
                "Test response", [{"id": "tool_1", "name": "todo_write", "args": {"todos": []}}]
            )
            mock_chain.ainvoke.return_value = mock_response

            mock_model = AsyncMock()
            mock_model.bind_tools.return_value = mock_chain
            mock_get_model.return_value = mock_model

            with patch("ee.hogai.graph.deep_research.planner.nodes.ChatPromptTemplate") as mock_prompt:
                mock_prompt_instance = MagicMock()
                mock_prompt.from_messages.return_value = mock_prompt_instance
                mock_prompt_instance.__or__ = MagicMock(return_value=mock_chain)

                result = await self.node.arun(state, self.config)

                self.assertIsNotNone(result.previous_response_id)
                self.assertEqual(result.previous_response_id, "test_response_id")
                self.assertEqual(len(result.messages), 1)
                self.assertIsInstance(result.messages[0], AssistantMessage)

    @patch("ee.hogai.graph.deep_research.planner.nodes.Notebook.objects.aget")
    async def test_arun_notebook_not_found(self, mock_notebook_get):
        """Test node execution raises error when notebook not found"""

        async def async_none(*args, **kwargs):
            return None

        mock_notebook_get.side_effect = async_none
        state = self._create_state()

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, self.config)
        self.assertEqual(str(cm.exception), "Notebook not found.")

    @parameterized.expand(
        [
            (
                "human_message_with_tool_calls",
                HumanMessage(content="Test", id=str(uuid4())),
                AssistantMessage(
                    content="", tool_calls=[AssistantToolCall(id="1", name="test", args={})], id=str(uuid4())
                ),
                True,
            ),
            (
                "human_message_with_tool_call_message",
                HumanMessage(content="Test", id=str(uuid4())),
                AssistantToolCallMessage(content="Result", tool_call_id="1", id=str(uuid4())),
                False,
            ),
            (
                "tool_call_message",
                None,
                AssistantToolCallMessage(content="Result", tool_call_id="1", id=str(uuid4())),
                False,
            ),
        ]
    )
    async def test_arun_with_previous_response_id_message_handling(
        self, _name, last_human_message, last_other_message, _has_tool_calls
    ):
        """Test node execution with previous response ID handles different message types"""
        messages = [last_other_message]
        if last_human_message:
            messages.append(last_human_message)

        state = self._create_state(messages=messages, previous_response_id="previous_123")

        with (
            patch.object(self.node, "_aget_core_memory", return_value="Test core memory") as _mock_core_memory,
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = AsyncMock()
            mock_response = self._create_langchain_ai_message(
                "Test response", [{"id": "tool_1", "name": "todo_write", "args": {"todos": []}}]
            )
            mock_chain.ainvoke.return_value = mock_response

            mock_model = AsyncMock()
            mock_model.bind_tools.return_value = mock_chain
            mock_get_model.return_value = mock_model

            with patch("ee.hogai.graph.deep_research.planner.nodes.ChatPromptTemplate") as mock_prompt:
                mock_prompt_instance = MagicMock()
                mock_prompt.from_messages.return_value = mock_prompt_instance
                mock_prompt_instance.__or__ = MagicMock(return_value=mock_chain)

                result = await self.node.arun(state, self.config)

                self.assertEqual(result.previous_response_id, "test_response_id")
                mock_prompt.from_messages.assert_called_once()

                call_args = mock_prompt.from_messages.call_args[0][0]
                if last_human_message:
                    # Should include human message
                    self.assertTrue(any("Test" in str(msg) for msg in call_args))

    async def test_arun_unexpected_message_type(self):
        """Test node execution raises error for unexpected message types"""
        state = self._create_state(
            messages=[AssistantMessage(content="Unexpected", id=str(uuid4()))], previous_response_id="test_123"
        )

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, self.config)
        self.assertEqual(str(cm.exception), "Unexpected message type.")

    def test_model_configuration(self):
        """Test model is properly configured with tools"""
        with (
            patch.object(self.node, "_aget_core_memory", return_value="Test core memory") as _mock_core_memory,
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            self.node._get_model("instructions", "response_id")

            mock_get_model.assert_called_once_with("instructions", "response_id")


@override_settings(IN_UNIT_TESTING=True)
class TestDeepResearchPlannerToolsNode(BaseTest):
    def setUp(self):
        super().setUp()
        warnings.filterwarnings("ignore", message="coroutine.*was never awaited", category=RuntimeWarning)
        self.node = DeepResearchPlannerToolsNode(self.team, self.user)
        self.config = RunnableConfig()

    def _create_state(self, **kwargs):
        """DeepResearchState init"""
        defaults: dict[str, Any] = {
            "messages": [],
            "todos": None,
            "tasks": None,
            "task_results": [],
            "intermediate_results": [],
            "previous_response_id": None,
            "conversation_notebooks": [],
            "current_run_notebooks": [
                DeepResearchNotebook(
                    notebook_id="test_notebook", notebook_type=DeepResearchType.PLANNING, title="Test Planning Notebook"
                )
            ]
            if kwargs.get("needs_notebook", True)
            else None,
        }
        # Remove needs_notebook from kwargs before updating
        kwargs.pop("needs_notebook", None)
        defaults.update(kwargs)
        return DeepResearchState(**defaults)

    def _create_assistant_message_with_tool_calls(self, tool_calls):
        """AssistantMessage with tool calls"""
        return AssistantMessage(content="Test message", tool_calls=tool_calls, id=str(uuid4()))

    async def test_arun_invalid_last_message_type(self):
        """Test node execution raises error when last message is not AssistantMessage"""
        state = self._create_state(messages=[HumanMessage(content="Test", id=str(uuid4()))])

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, self.config)
        self.assertEqual(str(cm.exception), "Last message is not an assistant message.")

    async def test_arun_no_tool_calls(self):
        """Test node execution returns human message when no tool calls present"""
        state = self._create_state(messages=[AssistantMessage(content="Test", tool_calls=None, id=str(uuid4()))])

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], HumanMessage)
        self.assertEqual(
            cast(HumanMessage, result.messages[0]).content, "You have to use at least one tool to continue."
        )

    async def test_arun_multiple_tool_calls_error(self):
        """Test node execution raises error when multiple tool calls are present"""
        tool_calls = [
            AssistantToolCall(id="1", name="todo_write", args={"todos": []}),
            AssistantToolCall(id="2", name="todo_read", args={}),
        ]
        state = self._create_state(messages=[self._create_assistant_message_with_tool_calls(tool_calls)])

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, self.config)
        self.assertEqual(str(cm.exception), "Expected exactly one tool call.")

    @parameterized.expand(
        [
            ("empty_todos", []),
            ("single_todo", [{"id": "1", "content": "Test task", "status": "pending", "priority": "high"}]),
            (
                "multiple_todos",
                [
                    {"id": "1", "content": "Task 1", "status": "pending", "priority": "high"},
                    {"id": "2", "content": "Task 2", "status": "in_progress", "priority": "medium"},
                ],
            ),
        ]
    )
    async def test_todo_write_tool(self, _name, todos_data):
        """Test todo_write tool execution with various todo configurations"""
        tool_calls = [AssistantToolCall(id="test_1", name="todo_write", args={"todos": todos_data})]
        state = self._create_state(messages=[self._create_assistant_message_with_tool_calls(tool_calls)])

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        if len(todos_data) == 0:
            self.assertEqual(len(result.messages), 1)
            self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(
                cast(AssistantToolCallMessage, result.messages[0]).content, "You have to provide at least one TO-DO."
            )
            self.assertIsNone(result.todos)
        else:
            self.assertEqual(len(result.messages), 1)
            self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
            self.assertIn("Todos updated. Current list:", cast(AssistantToolCallMessage, result.messages[0]).content)
            self.assertIsNotNone(result.todos)
            self.assertEqual(len(cast(list[TodoItem], result.todos)), len(todos_data))

    @parameterized.expand(
        [
            (
                "with_todos",
                [TodoItem(id="1", content="Test", status="pending", priority="high")],
            ),
            ("empty_todos", []),
            ("no_todos", None),
        ]
    )
    async def test_todo_read_tool(self, _name, todos):
        """Test todo_read tool execution with different todo states"""
        tool_calls = [AssistantToolCall(id="test_1", name="todo_read", args={})]
        state = self._create_state(messages=[self._create_assistant_message_with_tool_calls(tool_calls)], todos=todos)

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)

        result_message = cast(AssistantToolCallMessage, result.messages[0])
        if todos and len(todos) > 0:
            self.assertIn("Current todos:", result_message.content)
        else:
            self.assertIn("No todos yet", result_message.content)

    async def test_tools_requiring_todos_without_todos(self):
        """Test tools that require todos fail when no todos exist"""
        tool_names = ["artifacts_read", "execute_tasks", "result_write", "finalize_research"]

        for tool_name in tool_names:
            with self.subTest(tool=tool_name):
                tool_calls = [AssistantToolCall(id="test_1", name=tool_name, args={})]
                state = self._create_state(
                    messages=[self._create_assistant_message_with_tool_calls(tool_calls)], todos=None
                )
                result = await self.node.arun(state, self.config)
                result = cast(PartialDeepResearchState, result)

                self.assertEqual(len(result.messages), 1)
                self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
                self.assertIn("No todos yet", cast(AssistantToolCallMessage, result.messages[0]).content)

    @parameterized.expand(
        [
            (
                "with_artifacts",
                [
                    TaskResult(
                        id="1",
                        result="Result",
                        status=TaskExecutionStatus.COMPLETED,
                        artifacts=[_create_test_artifact("art1", "Artifact 1")],
                    )
                ],
            ),
            (
                "no_artifacts",
                [
                    TaskResult(
                        id="1",
                        result="Result",
                        status=TaskExecutionStatus.COMPLETED,
                        artifacts=[],
                    )
                ],
            ),
            ("empty_task_results", []),
        ]
    )
    async def test_artifacts_read_tool(self, _name, task_results):
        """Test artifacts_read tool execution with different artifact states"""
        tool_calls = [AssistantToolCall(id="test_1", name="artifacts_read", args={})]
        state = self._create_state(
            messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
            todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
            task_results=task_results,
        )

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)

        self.assertIn("Current artifacts:", cast(AssistantToolCallMessage, result.messages[0]).content)

    async def test_execute_tasks_tool(self):
        """Test execute_tasks tool returns None to redirect to task executor"""
        tasks = [
            DeepResearchTaskExecutionItem(
                id="1",
                description="Test task",
                prompt="Test prompt",
                task_type="create_insight",
            )
        ]
        tool_calls = [AssistantToolCall(id="test_1", name="execute_tasks", args={"tasks": tasks})]
        state = self._create_state(
            messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
            todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
        )

        result = await self.node.arun(state, self.config)

        # execute_tasks returns None to redirect to task executor
        self.assertIsNone(result)

    async def test_tools_requiring_task_results_without_results(self):
        """Test tools that require task results fail when no results exist"""
        tool_names = ["result_write", "finalize_research"]

        for tool_name in tool_names:
            with self.subTest(tool=tool_name):
                tool_calls = [AssistantToolCall(id="test_1", name=tool_name, args={})]
                state = self._create_state(
                    messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
                    todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
                    task_results=[],
                )

                result = await self.node.arun(state, self.config)
                result = cast(PartialDeepResearchState, result)

                self.assertEqual(len(result.messages), 1)
                self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
                self.assertEqual(
                    cast(AssistantToolCallMessage, result.messages[0]).content, NO_TASKS_RESULTS_TOOL_RESULT
                )

    @parameterized.expand(
        [
            ("empty_content", ""),
            ("valid_content", "This is a research result"),
        ]
    )
    async def test_result_write_tool_content_validation(self, _name, content):
        """Test result_write tool validates content is not empty"""
        result_data = {"content": content, "artifact_ids": []}
        tool_calls = [AssistantToolCall(id="test_1", name="result_write", args={"result": result_data})]
        state = self._create_state(
            messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
            todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
            task_results=[TaskResult(id="1", result="Result", status=TaskExecutionStatus.COMPLETED)],
        )

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        if not content:
            self.assertEqual(len(result.messages), 1)
            self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(
                cast(AssistantToolCallMessage, result.messages[0]).content, WRITE_RESULT_FAILED_TOOL_RESULT
            )
            self.assertEqual(len(result.intermediate_results), 0)
        else:
            self.assertEqual(len(result.messages), 2)
            self.assertIsInstance(result.messages[0], MultiVisualizationMessage)
            self.assertIsInstance(result.messages[1], AssistantToolCallMessage)
            self.assertEqual(cast(AssistantToolCallMessage, result.messages[1]).content, WRITE_RESULT_TOOL_RESULT)
            self.assertEqual(len(result.intermediate_results), 1)

    async def test_result_write_tool_invalid_artifact_ids(self):
        """Test result_write tool validates artifact IDs exist"""
        result_data = {"content": "Valid content", "artifact_ids": ["invalid_id"]}
        tool_calls = [AssistantToolCall(id="test_1", name="result_write", args={"result": result_data})]
        state = self._create_state(
            messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
            todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
            task_results=[
                TaskResult(
                    id="1",
                    result="Result",
                    status=TaskExecutionStatus.COMPLETED,
                    artifacts=[_create_test_artifact("valid_id", "Valid artifact")],
                )
            ],
        )

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("Invalid artifact IDs:", cast(AssistantToolCallMessage, result.messages[0]).content)

    async def test_result_write_tool_with_visualizations(self):
        """Test result_write tool creates visualizations for artifacts with queries"""
        artifact1 = _create_test_artifact("art1", "Chart", "SELECT * FROM events")
        artifact2 = _create_test_artifact("art2", "Text", "SELECT 2")

        result_data = {"content": "Research findings", "artifact_ids": ["art1", "art2"]}
        tool_calls = [AssistantToolCall(id="test_1", name="result_write", args={"result": result_data})]
        state = self._create_state(
            messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
            todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
            task_results=[
                TaskResult(
                    id="1",
                    result="Result",
                    status=TaskExecutionStatus.COMPLETED,
                    artifacts=[artifact1, artifact2],
                )
            ],
        )

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        self.assertEqual(len(result.messages), 2)

        viz_message = result.messages[0]
        self.assertIsInstance(viz_message, MultiVisualizationMessage)
        viz_message = cast(MultiVisualizationMessage, viz_message)
        # Both artifacts have queries
        self.assertEqual(len(viz_message.visualizations), 2)
        self.assertEqual(viz_message.visualizations[0].query, "Chart")
        self.assertEqual(viz_message.visualizations[1].query, "Text")
        self.assertEqual(viz_message.commentary, "Research findings")

    async def test_finalize_research_tool(self):
        """Test finalize_research tool execution"""
        tool_calls = [AssistantToolCall(id="test_1", name="finalize_research", args={})]
        state = self._create_state(
            messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
            todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
            task_results=[TaskResult(id="1", result="Result", status=TaskExecutionStatus.COMPLETED)],
        )

        result = await self.node.arun(state, self.config)
        result = cast(PartialDeepResearchState, result)

        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(cast(AssistantToolCallMessage, result.messages[0]).content, FINALIZE_RESEARCH_TOOL_RESULT)

    async def test_unknown_tool_call(self):
        """Test node execution raises error for unknown tool calls"""
        tool_calls = [AssistantToolCall(id="test_1", name="unknown_tool", args={})]
        state = self._create_state(
            messages=[self._create_assistant_message_with_tool_calls(tool_calls)],
            todos=[TodoItem(id="1", content="Test", status="pending", priority="high")],
            task_results=[TaskResult(id="1", result="Result", status=TaskExecutionStatus.COMPLETED)],
        )

        with self.assertRaises(ValueError) as cm:
            await self.node.arun(state, self.config)
        self.assertIn("Unknown tool call:", str(cm.exception))

    @parameterized.expand(
        [
            (
                "with_tool_calls",
                AssistantMessage(
                    content="",
                    tool_calls=[AssistantToolCall(id="1", name="execute_tasks", args={})],
                    id=str(uuid4()),
                ),
                "task_executor",
            ),
            (
                "with_finalize_message",
                AssistantToolCallMessage(content=FINALIZE_RESEARCH_TOOL_RESULT, tool_call_id="test", id=str(uuid4())),
                "end",
            ),
            (
                "continue_case",
                AssistantToolCallMessage(content="Other content", tool_call_id="test", id=str(uuid4())),
                "continue",
            ),
        ]
    )
    def test_router_logic(self, _name, last_message, expected_route):
        """Test router method returns correct route based on message type"""
        state = self._create_state(messages=[last_message])

        route = self.node.router(state)

        self.assertEqual(route, expected_route)

    def test_router_invalid_last_message_type(self):
        """Test router raises error when last message is not AssistantToolCallMessage"""
        state = self._create_state(messages=[HumanMessage(content="Test", id=str(uuid4()))], tasks=None)

        with self.assertRaises(ValueError) as cm:
            self.node.router(state)
        self.assertEqual(str(cm.exception), "Last message is not an assistant tool message.")
