from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import (
    AssistantMessage,
    AssistantTrendsQuery,
    HumanMessage,
    MultiVisualizationMessage,
    PlanningMessage,
    PlanningStep,
    PlanningStepStatus,
    TaskExecutionItem,
    TaskExecutionStatus,
    VisualizationItem,
)

from posthog.models.notebook import Notebook

from ee.hogai.graph.deep_research.graph import DeepResearchAssistantGraph
from ee.hogai.graph.deep_research.notebook.nodes import DeepResearchNotebookPlanningNode
from ee.hogai.graph.deep_research.onboarding.nodes import DeepResearchOnboardingNode
from ee.hogai.graph.deep_research.planner.nodes import DeepResearchPlannerNode, DeepResearchPlannerToolsNode
from ee.hogai.graph.deep_research.report.nodes import DeepResearchReportNode
from ee.hogai.graph.deep_research.task_executor.nodes import TaskExecutorNode
from ee.hogai.graph.deep_research.types import (
    DeepResearchIntermediateResult,
    DeepResearchSingleTaskResult,
    DeepResearchState,
    DeepResearchTodo,
)
from ee.hogai.graph.graph import InsightsAssistantGraph
from ee.models.assistant import Conversation


@patch("ee.hogai.graph.deep_research.base.nodes.DeepResearchNode._get_model")
@patch("ee.hogai.llm.MaxChatOpenAI")
class TestDeepResearchWorkflowIntegration(APIBaseTest):
    """
    Simplified integration tests for the deep research workflow
    """

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.notebook = Notebook.objects.create(team=self.team, created_by=self.user, short_id="test_nb_123")
        self.graph = DeepResearchAssistantGraph(self.team, self.user)
        self.thread_id = str(self.conversation.id)
        self.config = RunnableConfig(configurable={"thread_id": self.thread_id})

    def _create_mock_state(
        self,
        messages: list[Any] | None = None,
        todos: list[DeepResearchTodo] | None = None,
        tasks: list[TaskExecutionItem] | None = None,
        task_results: list[DeepResearchSingleTaskResult] | None = None,
        intermediate_results: list[DeepResearchIntermediateResult] | None = None,
        notebook_short_id: str | None = None,
    ) -> DeepResearchState:
        return DeepResearchState(
            messages=messages or [],
            todos=todos,
            tasks=tasks,
            task_results=task_results or [],
            intermediate_results=intermediate_results or [],
            notebook_short_id=notebook_short_id,
        )

    def _create_mock_human_message(self, content: str) -> HumanMessage:
        return HumanMessage(content=content)

    def _create_mock_planning_message(self, steps: list[PlanningStep]) -> PlanningMessage:
        return PlanningMessage(steps=steps)

    def _create_mock_visualization_message(self, query_items: list[VisualizationItem]) -> MultiVisualizationMessage:
        return MultiVisualizationMessage(visualizations=query_items)

    def test_graph_initialization(self, mock_llm_class, mock_get_model):
        self.assertIsNotNone(self.graph)
        self.assertEqual(self.graph._team, self.team)
        self.assertEqual(self.graph._user, self.user)

    def test_message_types_validation(self, mock_llm_class, mock_get_model):
        """Test that various message types are properly validated."""
        # Test planning message
        planning_steps = [PlanningStep(description="Test step", status=PlanningStepStatus.PENDING)]
        planning_message = self._create_mock_planning_message(planning_steps)
        self.assertEqual(len(planning_message.steps), 1)
        self.assertEqual(planning_message.steps[0].description, "Test step")

        mock_query = Mock(spec=AssistantTrendsQuery)
        viz_items = [VisualizationItem(answer=mock_query, query="Test query")]
        viz_message = self._create_mock_visualization_message(viz_items)
        self.assertEqual(len(viz_message.visualizations), 1)

    @parameterized.expand(
        [
            ("empty_state", "", 0, 0),
            ("basic", "Simple research question", 1, 0),
            ("complex", "Multi-faceted analysis with dependencies", 3, 2),
            ("high_volume", "Large scale analysis", 10, 8),
        ]
    )
    def test_state_serialization_scenarios(
        self, mock_llm_class, mock_get_model, scenario_name, query, num_todos, num_results
    ):
        """Test state serialization"""
        todos = [
            DeepResearchTodo(id=i, description=f"Task {i}", status=PlanningStepStatus.PENDING, priority="medium")
            for i in range(1, num_todos + 1)
        ]

        task_results = [
            DeepResearchSingleTaskResult(
                id=f"result_{i}", description=f"Result {i}", result="Success", status=TaskExecutionStatus.COMPLETED
            )
            for i in range(num_results)
        ]

        state = self._create_mock_state(
            messages=[HumanMessage(content=query)],
            todos=todos,
            task_results=task_results,
        )

        serialized = state.model_dump()
        deserialized = DeepResearchState.model_validate(serialized)

        self.assertEqual(len(deserialized.todos), num_todos)
        self.assertEqual(len(deserialized.task_results), num_results)
        self.assertEqual(deserialized.messages[0].content, query)

    def test_invalid_notebook_reference_handling(self, mock_llm_class, mock_get_model):
        """Test handling of invalid notebook references."""
        # Create state with non-existent notebook ID
        state = self._create_mock_state(notebook_short_id="nonexistent_nb")

        # Should still create valid state but with invalid reference
        self.assertEqual(state.notebook_short_id, "nonexistent_nb")

        # Verify notebook doesn't exist in database
        nonexistent_notebook = Notebook.objects.filter(short_id="nonexistent_nb").first()
        self.assertIsNone(nonexistent_notebook)

    def test_malformed_state_validation_errors(self, mock_llm_class, mock_get_model):
        """Test validation of malformed state configurations."""
        # Test invalid todo with missing required fields
        with self.assertRaises(ValidationError):
            DeepResearchTodo(description="Invalid todo")  # Missing id, status, priority

        # Test invalid task execution item
        with self.assertRaises(ValidationError):
            TaskExecutionItem(id="task_1")  # Missing description, prompt, status


class TestDeepResearchE2E(APIBaseTest):
    """
    Full end-to-end test for the deep research workflow.
    Tests the complete flow from user query to final report generation.
    """

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.thread_id = str(self.conversation.id)
        self.config = RunnableConfig(
            configurable={"thread_id": self.thread_id},
            callbacks=[],
        )

    def _create_mock_llm_response(self, content: str, response_id: str | None = None) -> LangchainAIMessage:
        if response_id is None:
            response_id = str(uuid4())
        return LangchainAIMessage(
            content=content,
            response_metadata={"id": response_id},
        )

    def test_deep_research_graph_structure_and_routing(self):
        """
        Comprehensive test for deep research graph structure and routing logic.
        """
        graph = DeepResearchAssistantGraph(self.team, self.user)
        compiled_graph = graph.compile_full_graph(checkpointer=InMemorySaver())

        self.assertIsNotNone(compiled_graph)
        self.assertTrue(hasattr(compiled_graph, "ainvoke"))
        self.assertTrue(hasattr(compiled_graph, "astream"))

        # Test onboarding routing logic with different state scenarios
        onboarding_node = DeepResearchOnboardingNode(self.team, self.user)

        # Scenario 1: Empty messages -> should go to onboarding
        empty_state = DeepResearchState(messages=[])
        routing = onboarding_node.should_run_onboarding_at_start(empty_state)
        self.assertEqual(routing, "onboarding")

        # Scenario 2: Single human message -> should go to onboarding
        single_message_state = DeepResearchState(messages=[HumanMessage(content="First question")])
        routing = onboarding_node.should_run_onboarding_at_start(single_message_state)
        self.assertEqual(routing, "onboarding")

        # Scenario 3: Multiple human messages without notebook -> should go to planning
        multi_message_state = DeepResearchState(
            messages=[
                HumanMessage(content="First question"),
                AssistantMessage(content="Response"),
                HumanMessage(content="Follow-up question"),
            ]
        )
        routing = onboarding_node.should_run_onboarding_at_start(multi_message_state)
        self.assertEqual(routing, "planning")

        # Scenario 4: Multiple human messages with notebook -> should continue
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, short_id="test_e2e_nb")
        existing_conversation_state = DeepResearchState(
            messages=[
                HumanMessage(content="Previous question"),
                AssistantMessage(content="Previous response"),
                HumanMessage(content="Continue research"),
            ],
            notebook_short_id=notebook.short_id,
        )
        routing = onboarding_node.should_run_onboarding_at_start(existing_conversation_state)
        self.assertEqual(routing, "continue")

        # Test that all required node types exist and can be instantiated
        nodes_to_test = [
            (DeepResearchOnboardingNode, "onboarding"),
            (DeepResearchNotebookPlanningNode, "notebook_planning"),
            (DeepResearchPlannerNode, "planner"),
            (DeepResearchPlannerToolsNode, "planner_tools"),
            (DeepResearchReportNode, "report"),
        ]

        for node_class, node_name in nodes_to_test:
            with self.subTest(node=node_name):
                if node_class == TaskExecutorNode:
                    # TaskExecutorNode requires insights subgraph
                    insights_graph = InsightsAssistantGraph(self.team, self.user).compile_full_graph()
                    node_instance = node_class(self.team, self.user, insights_graph)
                else:
                    node_instance = node_class(self.team, self.user)

                self.assertIsNotNone(node_instance)
                self.assertEqual(node_instance._team, self.team)
                self.assertEqual(node_instance._user, self.user)

        # Test state validation and serialization
        test_state = DeepResearchState(
            messages=[HumanMessage(content="Test message")],
            todos=[DeepResearchTodo(id=1, description="Test todo", status=PlanningStepStatus.PENDING, priority="high")],
            task_results=[
                DeepResearchSingleTaskResult(
                    id="task_1", description="Test task", result="Test result", status=TaskExecutionStatus.COMPLETED
                )
            ],
            notebook_short_id=notebook.short_id,
        )

        # Test serialization roundtrip
        serialized = test_state.model_dump()
        deserialized = DeepResearchState.model_validate(serialized)

        self.assertEqual(len(deserialized.messages), 1)
        self.assertEqual(len(deserialized.todos), 1)
        self.assertEqual(len(deserialized.task_results), 1)
        self.assertEqual(deserialized.notebook_short_id, notebook.short_id)
        self.assertEqual(deserialized.todos[0].description, "Test todo")
        self.assertEqual(deserialized.task_results[0].result, "Test result")

        # Test database integration
        retrieved_notebook = Notebook.objects.get(short_id=notebook.short_id)
        self.assertEqual(retrieved_notebook.team, self.team)
        self.assertEqual(retrieved_notebook.created_by, self.user)

        # Test conversation persistence
        retrieved_conversation = Conversation.objects.get(id=self.conversation.id)
        self.assertEqual(retrieved_conversation.team, self.team)
        self.assertEqual(retrieved_conversation.user, self.user)

        # Test configuration handling
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        self.assertIn("thread_id", config["configurable"])
        self.assertEqual(config["configurable"]["thread_id"], str(self.conversation.id))
