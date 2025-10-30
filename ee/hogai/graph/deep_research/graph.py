from typing import Any, Literal, Optional, cast

from posthog.models.team.team import Team
from posthog.models.user import User

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.deep_research.notebook.nodes import DeepResearchNotebookPlanningNode
from ee.hogai.graph.deep_research.onboarding.nodes import DeepResearchOnboardingNode
from ee.hogai.graph.deep_research.planner.nodes import DeepResearchPlannerNode, DeepResearchPlannerToolsNode
from ee.hogai.graph.deep_research.report.nodes import DeepResearchReportNode
from ee.hogai.graph.deep_research.task_executor.nodes import DeepResearchTaskExecutorNode
from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.graph.graph import BaseAssistantGraph
from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.types.base import AssistantNodeName, NodePath


class DeepResearchAssistantGraph(BaseAssistantGraph[DeepResearchState, PartialDeepResearchState]):
    def __init__(self, team: Team, user: User, node_path: tuple[NodePath, ...] | None = None):
        super().__init__(team, user, DeepResearchState, node_path)

    def add_onboarding_node(
        self, node_map: Optional[dict[Literal["onboarding", "planning", "continue"], DeepResearchNodeName]] = None
    ):
        builder = self._graph
        self._has_start_node = True
        deep_research_onboarding = DeepResearchOnboardingNode(self._team, self._user, self._node_path)
        builder.add_node(DeepResearchNodeName.ONBOARDING, deep_research_onboarding)
        builder.add_conditional_edges(
            DeepResearchNodeName.START,
            deep_research_onboarding.should_run_onboarding_at_start,
            node_map  # type: ignore
            or {
                "onboarding": DeepResearchNodeName.ONBOARDING,
                "planning": DeepResearchNodeName.NOTEBOOK_PLANNING,
                "continue": DeepResearchNodeName.PLANNER,
            },
        )
        return self

    def add_notebook_nodes(self, next_node: DeepResearchNodeName = DeepResearchNodeName.PLANNER):
        builder = self._graph

        deep_research_notebook_planning = DeepResearchNotebookPlanningNode(self._team, self._user, self._node_path)
        builder.add_node(DeepResearchNodeName.NOTEBOOK_PLANNING, deep_research_notebook_planning)
        builder.add_edge(DeepResearchNodeName.NOTEBOOK_PLANNING, next_node)

        return self

    def add_planner_nodes(self, next_node: DeepResearchNodeName = DeepResearchNodeName.REPORT):
        builder = self._graph
        deep_research_planner = DeepResearchPlannerNode(self._team, self._user, self._node_path)
        deep_research_planner_tools = DeepResearchPlannerToolsNode(self._team, self._user, self._node_path)
        builder.add_node(DeepResearchNodeName.PLANNER, deep_research_planner)
        builder.add_node(DeepResearchNodeName.PLANNER_TOOLS, deep_research_planner_tools)
        builder.add_edge(DeepResearchNodeName.PLANNER, DeepResearchNodeName.PLANNER_TOOLS)
        builder.add_conditional_edges(
            DeepResearchNodeName.PLANNER_TOOLS,
            deep_research_planner_tools.router,
            path_map={
                "task_executor": DeepResearchNodeName.TASK_EXECUTOR,
                "continue": DeepResearchNodeName.PLANNER,
                "end": next_node,
            },
        )

        return self

    def add_task_executor(self, next_node: DeepResearchNodeName = DeepResearchNodeName.PLANNER):
        """
        Add the core task executor node that handles task execution.
        """
        executor_node = DeepResearchTaskExecutorNode(self._team, self._user, self._node_path)
        self.add_node(DeepResearchNodeName.TASK_EXECUTOR, executor_node)
        self.add_edge(DeepResearchNodeName.TASK_EXECUTOR, next_node)
        return self

    def add_report_node(self, next_node: DeepResearchNodeName = DeepResearchNodeName.END):
        builder = self._graph
        deep_research_report = DeepResearchReportNode(self._team, self._user, self._node_path)
        builder.add_node(DeepResearchNodeName.REPORT, deep_research_report)
        builder.add_edge(DeepResearchNodeName.REPORT, next_node)
        return self

    def add_title_generator(self, end_node: DeepResearchNodeName = DeepResearchNodeName.END):
        self._has_start_node = True

        title_generator = TitleGeneratorNode(self._team, self._user, self._node_path)
        self.add_node(AssistantNodeName.TITLE_GENERATOR, cast(Any, title_generator))
        self._graph.add_edge(AssistantNodeName.START, AssistantNodeName.TITLE_GENERATOR)
        self._graph.add_edge(AssistantNodeName.TITLE_GENERATOR, end_node)
        return self

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        return (
            self.add_onboarding_node()
            .add_notebook_nodes()
            .add_planner_nodes()
            .add_report_node()
            .add_task_executor()
            .compile(checkpointer=checkpointer)
        )
