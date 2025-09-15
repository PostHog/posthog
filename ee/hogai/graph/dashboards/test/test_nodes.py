from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from posthog.schema import (
    AssistantHogQLQuery,
    AssistantToolCallMessage,
    TaskExecutionItem,
    TaskExecutionMessage,
    TaskExecutionStatus,
)

from posthog.models import Dashboard, Insight, Team, User

from ee.hogai.graph.dashboards.nodes import (
    DashboardCreatorNode,
    DashboardInsightCreationTaskExecutorNode,
    DashboardInsightSearchTaskExecutorNode,
    QueryMetadata,
)
from ee.hogai.graph.dashboards.types import (
    PartialDashboardInsightCreationTaskExecutionState,
    PartialDashboardInsightSearchTaskExecutionState,
)
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import (
    InsightCreationArtifact,
    InsightCreationTaskExecutionResult,
    InsightQuery,
    InsightSearchArtifact,
    InsightSearchTaskExecutionResult,
)


class TestQueryMetadata(TestCase):
    def test_query_metadata_initialization(self):
        """Test QueryMetadata initialization with all fields."""
        query = InsightQuery(name="Test Query", description="Test Description")
        metadata = QueryMetadata(
            found_insight_ids={1, 2, 3},
            created_insight_ids={4, 5},
            found_insight_messages=["Found message 1", "Found message 2"],
            created_insight_messages=["Created message 1"],
            query=query,
        )

        self.assertEqual(metadata.found_insight_ids, {1, 2, 3})
        self.assertEqual(metadata.created_insight_ids, {4, 5})
        self.assertEqual(metadata.found_insight_messages, ["Found message 1", "Found message 2"])
        self.assertEqual(metadata.created_insight_messages, ["Created message 1"])
        self.assertEqual(metadata.query, query)


class TestDashboardInsightSearchTaskExecutorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock(spec=Team)
        self.mock_team.id = 1
        self.mock_user = MagicMock(spec=User)
        self.mock_user.id = 1
        self.mock_executor = MagicMock()
        self.node = DashboardInsightSearchTaskExecutorNode(self.mock_team, self.mock_user, self.mock_executor)

    def test_initialization(self):
        """Test node initialization."""
        self.assertEqual(self.node._team, self.mock_team)
        self.assertEqual(self.node._user, self.mock_user)
        self.assertIsNotNone(self.node._execute_tasks_tool)

    def test_create_task_executor_tool_with_node_executor(self):
        """Test _create_task_executor_tool with AssistantNode executor."""
        from ee.hogai.graph.task_executor.tools import NodeTaskExecutorTool

        tool = self.node._create_task_executor_tool(self.mock_executor)
        self.assertIsInstance(tool, NodeTaskExecutorTool)

    def test_create_task_executor_tool_with_subgraph_executor_raises_error(self):
        """Test _create_task_executor_tool raises error with CompiledStateGraph."""
        mock_subgraph = MagicMock(spec=CompiledStateGraph)
        with self.assertRaises(ValueError) as cm:
            self.node._create_task_executor_tool(mock_subgraph)
        self.assertIn("SubgraphTaskExecutorTool only works with InsightCreationTaskExecutionResult", str(cm.exception))

    def test_get_node_name(self):
        """Test _get_node_name returns correct node name."""
        from ee.hogai.utils.types import AssistantNodeName

        node_name = self.node._get_node_name()
        self.assertEqual(node_name, AssistantNodeName.DASHBOARD_CREATOR)

    def test_create_final_response(self):
        """Test _create_final_response creates correct response."""
        task_results = [
            InsightSearchTaskExecutionResult(
                id="task_1",
                description="Test task",
                result="Task completed successfully",
                artifacts=[
                    InsightSearchArtifact(
                        id="art_1", description="Test artifact", insight_ids=[1, 2], selection_reason="Test reason"
                    )
                ],
                status=TaskExecutionStatus.COMPLETED,
            )
        ]
        tool_call_id = "test_tool_call"
        task_execution_message_id = "test_message_id"
        tasks = [
            TaskExecutionItem(
                id="task_1", description="Test task", prompt="Test prompt", status=TaskExecutionStatus.COMPLETED
            )
        ]

        result = self.node._create_final_response(task_results, tool_call_id, task_execution_message_id, tasks)

        self.assertIsInstance(result, PartialDashboardInsightSearchTaskExecutionState)
        self.assertEqual(len(result.messages), 2)
        self.assertIsInstance(result.messages[0], TaskExecutionMessage)
        assert isinstance(result.messages[1], AssistantToolCallMessage)
        self.assertEqual(result.messages[1].tool_call_id, tool_call_id)
        self.assertIn("Completed 1 insight search tasks successfully", result.messages[1].content)
        self.assertEqual(result.task_results, task_results)
        self.assertIsNone(result.tasks)

    def test_create_empty_response(self):
        """Test _create_empty_response creates correct empty response."""
        tool_call_id = "test_tool_call"
        result = self.node._create_empty_response(tool_call_id)

        self.assertIsInstance(result, PartialDashboardInsightSearchTaskExecutionState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)

        self.assertEqual(result.messages[0].tool_call_id, tool_call_id)
        self.assertEqual(result.messages[0].content, "No tasks to execute")


class TestDashboardInsightCreationTaskExecutorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock(spec=Team)
        self.mock_team.id = 1
        self.mock_user = MagicMock(spec=User)
        self.mock_user.id = 1
        self.mock_subgraph = MagicMock(spec=CompiledStateGraph)
        self.node = DashboardInsightCreationTaskExecutorNode(self.mock_team, self.mock_user, self.mock_subgraph)

    def test_initialization(self):
        """Test node initialization."""
        self.assertEqual(self.node._team, self.mock_team)
        self.assertEqual(self.node._user, self.mock_user)
        self.assertIsNotNone(self.node._execute_tasks_tool)

    def test_create_task_executor_tool_with_subgraph_executor(self):
        """Test _create_task_executor_tool with CompiledStateGraph executor."""
        from ee.hogai.graph.task_executor.tools import SubgraphTaskExecutorTool

        tool = self.node._create_task_executor_tool(self.mock_subgraph)
        self.assertIsInstance(tool, SubgraphTaskExecutorTool)

    def test_create_task_executor_tool_with_node_executor_raises_error(self):
        """Test _create_task_executor_tool raises error with AssistantNode."""
        mock_node = MagicMock()
        with self.assertRaises(ValueError) as cm:
            self.node._create_task_executor_tool(mock_node)
        self.assertIn("NodeTaskExecutorTool only works with InsightCreationArtifact", str(cm.exception))

    def test_get_node_name(self):
        """Test _get_node_name returns correct node name."""
        from ee.hogai.utils.types import AssistantNodeName

        node_name = self.node._get_node_name()
        self.assertEqual(node_name, AssistantNodeName.DASHBOARD_CREATOR)

    def test_create_final_response(self):
        """Test _create_final_response creates correct response."""
        task_results = [
            InsightCreationTaskExecutionResult(
                id="task_1",
                description="Test task",
                result="Task completed successfully",
                artifacts=[
                    InsightCreationArtifact(
                        id="art_1", description="Test artifact", query=AssistantHogQLQuery(query="SELECT 1")
                    )
                ],
                status=TaskExecutionStatus.COMPLETED,
            ),
            InsightCreationTaskExecutionResult(
                id="task_2",
                description="Test task failed",
                result="Task completed with errors",
                artifacts=[
                    InsightCreationArtifact(
                        id="art_2", description="Test artifact", query=AssistantHogQLQuery(query="")
                    )
                ],
                status=TaskExecutionStatus.FAILED,
            ),
        ]
        tool_call_id = "test_tool_call"
        task_execution_message_id = "test_message_id"
        tasks = [
            TaskExecutionItem(
                id="task_1", description="Test task", prompt="Test prompt", status=TaskExecutionStatus.PENDING
            ),
            TaskExecutionItem(
                id="task_2", description="Test task", prompt="Test prompt", status=TaskExecutionStatus.PENDING
            ),
        ]

        result = self.node._create_final_response(task_results, tool_call_id, task_execution_message_id, tasks)

        self.assertIsInstance(result, PartialDashboardInsightCreationTaskExecutionState)
        self.assertEqual(len(result.messages), 2)
        self.assertIsInstance(result.messages[0], TaskExecutionMessage)
        assert isinstance(result.messages[1], AssistantToolCallMessage)
        self.assertEqual(result.messages[1].tool_call_id, tool_call_id)
        self.assertIn("Completed 2 insight creation tasks successfully", result.messages[1].content)
        self.assertEqual(result.task_results, task_results)
        self.assertIsNone(result.tasks)

    def test_create_empty_response(self):
        """Test _create_empty_response creates correct empty response."""
        tool_call_id = "test_tool_call"
        result = self.node._create_empty_response(tool_call_id)

        self.assertIsInstance(result, PartialDashboardInsightCreationTaskExecutionState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, tool_call_id)
        self.assertEqual(result.messages[0].content, "No tasks to execute")


class TestDashboardCreatorNode(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock(spec=Team)
        self.mock_team.id = 1
        self.mock_user = MagicMock(spec=User)
        self.mock_user.id = 1
        self.node = DashboardCreatorNode(self.mock_team, self.mock_user)

    def test_initialization(self):
        """Test node initialization."""
        self.assertEqual(self.node._team, self.mock_team)
        self.assertEqual(self.node._user, self.mock_user)
        self.assertIsNone(self.node._stream_writer)

    def test_get_stream_writer_success(self):
        """Test _get_stream_writer returns stream writer when available."""
        mock_writer = MagicMock()
        with patch("ee.hogai.graph.dashboards.nodes.get_stream_writer", return_value=mock_writer):
            writer = self.node._get_stream_writer()
            self.assertEqual(writer, mock_writer)

    def test_get_stream_writer_failure(self):
        """Test _get_stream_writer returns None when stream writer unavailable."""
        with patch("ee.hogai.graph.dashboards.nodes.get_stream_writer", side_effect=Exception("No writer")):
            writer = self.node._get_stream_writer()
            self.assertIsNone(writer)

    def test_stream_reasoning_with_writer(self):
        """Test _stream_reasoning with available writer."""
        mock_writer = MagicMock()
        progress_message = "Test progress"
        substeps = ["Step 1", "Step 2"]

        with patch("ee.hogai.graph.dashboards.nodes.get_stream_writer", return_value=mock_writer):
            self.node._stream_reasoning(progress_message, substeps, mock_writer)

            mock_writer.assert_called_once()
            call_args = mock_writer.call_args[0][0]
            self.assertEqual(call_args[0], "dashboard_creator_node")
            self.assertEqual(call_args[1], "messages")

    def test_stream_reasoning_without_writer(self):
        """Test _stream_reasoning without writer logs warning."""
        with patch("ee.hogai.graph.dashboards.nodes.logger") as mock_logger:
            self.node._stream_reasoning("Test progress", None, None)
            mock_logger.warning.assert_called_once_with("Cannot stream reasoning message!")

    def test_get_found_insight_count(self):
        """Test _get_found_insight_count calculates correct count."""
        queries_metadata = {
            "query_1": QueryMetadata(
                found_insight_ids={1, 2, 3},
                created_insight_ids=set(),
                found_insight_messages=[],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            ),
            "query_2": QueryMetadata(
                found_insight_ids={4, 5},
                created_insight_ids=set(),
                found_insight_messages=[],
                created_insight_messages=[],
                query=InsightQuery(name="Query 2", description="Description 2"),
            ),
        }

        count = self.node._get_found_insight_count(queries_metadata)
        self.assertEqual(count, 5)  # 3 + 2

    def test_build_insight_url(self):
        """Test _build_insight_url creates correct URL."""
        insight_id = "test_insight_id"
        url = self.node._build_insight_url(insight_id)
        expected_url = f"/project/{self.mock_team.id}/insights/{insight_id}"
        self.assertEqual(url, expected_url)

    def test_build_dashboard_url(self):
        """Test _build_dashboard_url creates correct URL."""
        dashboard_id = 123
        url = self.node._build_dashboard_url(dashboard_id)
        expected_url = f"/project/{self.mock_team.id}/dashboard/{dashboard_id}"
        self.assertEqual(url, expected_url)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    async def test_arun_missing_create_dashboard_query(self, mock_get_stream_writer):
        """Test arun returns error when create_dashboard_query is missing."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        state = AssistantState(
            create_dashboard_query=None,
            search_insights_queries=[InsightQuery(name="Test", description="Test")],
            root_tool_call_id="test_call",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("Dashboard creation query is required", result.messages[0].content)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    async def test_arun_missing_search_insights_queries(self, mock_get_stream_writer):
        """Test arun returns error when search_insights_queries is missing."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        state = AssistantState(
            create_dashboard_query="Create dashboard",
            search_insights_queries=None,
            root_tool_call_id="test_call",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("Search insights queries are required", result.messages[0].content)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch.object(DashboardCreatorNode, "_search_insights")
    @patch.object(DashboardCreatorNode, "_create_insights")
    @patch.object(DashboardCreatorNode, "_generate_dashboard_name")
    @patch.object(DashboardCreatorNode, "_create_dashboard_with_insights")
    async def test_arun_successful_flow(
        self,
        mock_create_dashboard,
        mock_generate_name,
        mock_create_insights,
        mock_search_insights,
        mock_get_stream_writer,
    ):
        """Test successful arun flow with found insights."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        # Setup mocks
        mock_dashboard = MagicMock(spec=Dashboard)
        mock_dashboard.id = 1
        mock_dashboard.name = "Test Dashboard"
        mock_insights = [MagicMock(spec=Insight), MagicMock(spec=Insight)]
        mock_insights[0].short_id = "insight_1"
        mock_insights[0].name = "Insight 1"
        mock_insights[1].short_id = "insight_2"
        mock_insights[1].name = "Insight 2"

        mock_create_dashboard.return_value = (mock_dashboard, mock_insights)
        mock_generate_name.return_value = "Test Dashboard"

        # Setup search results with found insights
        search_result = {
            "query_1": QueryMetadata(
                found_insight_ids={1, 2},
                created_insight_ids=set(),
                found_insight_messages=["Found insights"],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            )
        }
        mock_search_insights.return_value = search_result
        mock_create_insights.return_value = search_result

        state = AssistantState(
            create_dashboard_query="Create dashboard",
            search_insights_queries=[InsightQuery(name="Query 1", description="Description 1")],
            root_tool_call_id="test_call",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("Dashboard Created", result.messages[0].content)
        self.assertIn("Test Dashboard", result.messages[0].content)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch.object(DashboardCreatorNode, "_search_insights")
    @patch.object(DashboardCreatorNode, "_create_insights")
    async def test_arun_no_insights_found_or_created(
        self, mock_create_insights, mock_search_insights, mock_get_stream_writer
    ):
        """Test arun when no insights are found or created."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        # Setup search results with no insights
        search_result = {
            "query_1": QueryMetadata(
                found_insight_ids=set(),
                created_insight_ids=set(),
                found_insight_messages=["No insights found"],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            )
        }
        mock_search_insights.return_value = search_result
        mock_create_insights.return_value = search_result

        state = AssistantState(
            create_dashboard_query="Create dashboard",
            search_insights_queries=[InsightQuery(name="Query 1", description="Description 1")],
            root_tool_call_id="test_call",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("No existing insights matched", result.messages[0].content)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch.object(DashboardCreatorNode, "_search_insights")
    @patch("ee.hogai.graph.dashboards.nodes.logger")
    async def test_arun_exception_handling(self, mock_logger, mock_search_insights, mock_get_stream_writer):
        """Test arun handles exceptions properly."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer
        mock_search_insights.side_effect = Exception("Test error")

        state = AssistantState(
            create_dashboard_query="Create dashboard",
            search_insights_queries=[InsightQuery(name="Query 1", description="Description 1")],
            root_tool_call_id="test_call",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("I encountered an issue while creating the dashboard", result.messages[0].content)
        mock_logger.exception.assert_called_once()

    def test_create_success_response(self):
        """Test _create_success_response creates correct success message."""
        mock_dashboard = MagicMock(spec=Dashboard)
        mock_dashboard.id = 1
        mock_dashboard.name = "Test Dashboard"

        mock_insights = [MagicMock(spec=Insight), MagicMock(spec=Insight)]
        mock_insights[0].short_id = "insight_1"
        mock_insights[0].name = "Insight 1"
        mock_insights[1].short_id = "insight_2"
        mock_insights[1].name = "Insight 2"

        result = self.node._create_success_response(
            mock_dashboard,
            mock_insights,  # type: ignore[arg-type]
            "test_call",
            ["Query without insights"],
        )

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("Dashboard Created", result.messages[0].content)
        self.assertIn("Test Dashboard", result.messages[0].content)
        self.assertIn("2 insights", result.messages[0].content)
        self.assertIn("Query without insights", result.messages[0].content)

    def test_create_no_insights_response(self):
        """Test _create_no_insights_response creates correct no insights message."""
        result = self.node._create_no_insights_response("test_call", "No insights found")

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertIn("No existing insights matched", result.messages[0].content)
        self.assertIn("No insights found", result.messages[0].content)

    def test_create_error_response(self):
        """Test _create_error_response creates correct error message."""
        with patch("ee.hogai.graph.dashboards.nodes.capture_exception") as mock_capture:
            result = self.node._create_error_response("Test error", "test_call")

            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(len(result.messages), 1)
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(result.messages[0].content, "Test error")
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(result.messages[0].tool_call_id, "test_call")
            mock_capture.assert_called_once()


class TestDashboardCreatorNodeAsyncMethods(TestCase):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock(spec=Team)
        self.mock_team.id = 1
        self.mock_user = MagicMock(spec=User)
        self.mock_user.id = 1
        self.node = DashboardCreatorNode(self.mock_team, self.mock_user)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch("ee.hogai.graph.dashboards.nodes.InsightsAssistantGraph")
    async def test_create_insights(self, mock_graph_class, mock_get_stream_writer):
        """Test _create_insights method."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        # Setup mocks
        mock_graph = MagicMock()
        mock_compiled_graph = MagicMock()
        mock_graph.compile_full_graph.return_value = mock_compiled_graph
        mock_graph_class.return_value = mock_graph

        mock_executor_node = MagicMock()
        mock_task_result = InsightCreationTaskExecutionResult(
            id="task_1",
            description="Test task",
            result="Task completed successfully",
            artifacts=[
                InsightCreationArtifact(id="art_1", description="Test", query=AssistantHogQLQuery(query="SELECT 1"))
            ],
            status=TaskExecutionStatus.COMPLETED,
        )
        mock_executor_node.arun.return_value = PartialDashboardInsightCreationTaskExecutionState(
            task_results=[mock_task_result]
        )

        with patch(
            "ee.hogai.graph.dashboards.nodes.DashboardInsightCreationTaskExecutorNode", return_value=mock_executor_node
        ):
            with patch.object(self.node, "_save_insights", return_value={"task_1": {1, 2}}):
                left_to_create = {"task_1": InsightQuery(name="Query 1", description="Description 1")}
                query_metadata = {
                    "task_1": QueryMetadata(
                        found_insight_ids=set(),
                        created_insight_ids=set(),
                        found_insight_messages=[],
                        created_insight_messages=[],
                        query=InsightQuery(name="Query 1", description="Description 1"),
                    )
                }

                state = AssistantState()
                config = RunnableConfig()

                result = await self.node._create_insights(left_to_create, query_metadata, state, config)

                self.assertIn("task_1", result)
                self.assertEqual(len(result["task_1"].created_insight_ids), 2)
                self.assertEqual(len(result["task_1"].created_insight_messages), 1)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch("ee.hogai.graph.dashboards.nodes.InsightSearchNode")
    async def test_search_insights(self, mock_search_node_class, mock_get_stream_writer):
        """Test _search_insights method."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        # Setup mocks
        mock_search_node = MagicMock()
        mock_search_node_class.return_value = mock_search_node

        mock_executor_node = MagicMock()
        mock_task_result = InsightSearchTaskExecutionResult(
            id="task_1",
            description="Test task",
            artifacts=[
                InsightSearchArtifact(
                    id="art_1", insight_ids={1, 2}, selection_reason="Test reason", description="Test task"
                )
            ],
            status=TaskExecutionStatus.COMPLETED,
            result="Task completed successfully",
        )
        mock_executor_node.arun.return_value = PartialDashboardInsightSearchTaskExecutionState(
            task_results=[mock_task_result]
        )

        with patch(
            "ee.hogai.graph.dashboards.nodes.DashboardInsightSearchTaskExecutorNode", return_value=mock_executor_node
        ):
            queries_metadata = {
                "task_1": QueryMetadata(
                    found_insight_ids=set(),
                    created_insight_ids=set(),
                    found_insight_messages=[],
                    created_insight_messages=[],
                    query=InsightQuery(name="Query 1", description="Description 1"),
                )
            }

            state = AssistantState()
            config = RunnableConfig()

            result = await self.node._search_insights(queries_metadata, state, config)

            self.assertIn("task_1", result)
            self.assertEqual(len(result["task_1"].found_insight_ids), 2)
            self.assertEqual(len(result["task_1"].found_insight_messages), 1)

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch.object(DashboardCreatorNode, "_model")
    async def test_generate_dashboard_name_success(self, mock_model, mock_get_stream_writer):
        """Test _generate_dashboard_name with successful generation."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        mock_response = MagicMock()
        mock_response.content = "User Engagement Dashboard"
        mock_model.ainvoke.return_value = mock_response

        result = await self.node._generate_dashboard_name("Create user engagement dashboard", ["Found insights"])

        self.assertEqual(result, "User Engagement Dashboard")
        mock_model.ainvoke.assert_called_once()

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch.object(DashboardCreatorNode, "_model")
    async def test_generate_dashboard_name_exception(self, mock_model, mock_get_stream_writer):
        """Test _generate_dashboard_name handles exceptions."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer
        mock_model.ainvoke.side_effect = Exception("Model error")

        with patch("ee.hogai.graph.dashboards.nodes.capture_exception") as mock_capture:
            with patch("ee.hogai.graph.dashboards.nodes.logger") as mock_logger:
                result = await self.node._generate_dashboard_name("Create dashboard", [])

                self.assertEqual(result, "Analytics Dashboard")
                mock_capture.assert_called_once()
                mock_logger.exception.assert_called_once()

    @patch("ee.hogai.graph.dashboards.nodes.get_stream_writer")
    @patch("ee.hogai.graph.dashboards.nodes.database_sync_to_async")
    async def test_create_dashboard_with_insights(self, mock_db_sync, mock_get_stream_writer):
        """Test _create_dashboard_with_insights method."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer

        mock_dashboard = MagicMock(spec=Dashboard)
        mock_dashboard.id = 1
        mock_dashboard.name = "Test Dashboard"

        mock_insights = [MagicMock(spec=Insight), MagicMock(spec=Insight)]
        mock_insights[0].id = 1
        mock_insights[1].id = 2

        mock_sync_func = AsyncMock(return_value=(mock_dashboard, mock_insights))
        mock_db_sync.return_value = mock_sync_func

        result = await self.node._create_dashboard_with_insights("Test Dashboard", {1, 2})

        self.assertEqual(result[0], mock_dashboard)
        self.assertEqual(result[1], mock_insights)
        mock_sync_func.assert_called_once()

    async def test_save_insights(self):
        """Test _save_insights method."""
        mock_insight1 = MagicMock(spec=Insight)
        mock_insight1.id = 1
        mock_insight2 = MagicMock(spec=Insight)
        mock_insight2.id = 2

        with patch(
            "ee.hogai.graph.dashboards.nodes.Insight.objects.bulk_create", return_value=[mock_insight1, mock_insight2]
        ):
            task_results = [
                InsightCreationTaskExecutionResult(
                    id="task_1",
                    description="Test task",
                    result="Task completed successfully",
                    artifacts=[
                        InsightCreationArtifact(
                            id="art_1", description="Test artifact", query=AssistantHogQLQuery(query="SELECT 1")
                        )
                    ],
                    status=TaskExecutionStatus.COMPLETED,
                )
            ]
            query_metadata = {
                "task_1": QueryMetadata(
                    found_insight_ids=set(),
                    created_insight_ids=set(),
                    found_insight_messages=[],
                    created_insight_messages=[],
                    query=InsightQuery(name="Query 1", description="Description 1"),
                )
            }

            result = await self.node._save_insights(task_results, query_metadata)

            self.assertIn("task_1", result)
            self.assertEqual(len(result["task_1"]), 2)
            self.assertIn(1, result["task_1"])
            self.assertIn(2, result["task_1"])
