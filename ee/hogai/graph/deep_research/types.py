from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Optional

from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.schema import PlanningStepStatus, TaskExecutionItem, TaskExecutionStatus

from ee.hogai.utils.types import AssistantMessageUnion, BaseState, InsightArtifact, add_and_merge_messages
from ee.hogai.utils.types.base import append, replace


class DeepResearchTodo(BaseModel):
    """
    A TO-DO item in the research plan.
    """

    id: int
    description: str
    status: PlanningStepStatus
    priority: Literal["low", "medium", "high"]


class DeepResearchSingleTaskResult(BaseModel):
    """
    The result of an individual task.
    """

    id: str
    description: str
    result: str
    artifacts: list[InsightArtifact] = Field(default=[])
    status: TaskExecutionStatus


class DeepResearchIntermediateResult(BaseModel):
    """
    An intermediate result of a batch of work, that will be used to write the final report.
    """

    content: str
    artifact_ids: list[str] = Field(default=[])


class _SharedDeepResearchState(BaseState):
    todos: Annotated[Optional[list[DeepResearchTodo]], replace] = Field(default=None)
    """
    The current TO-DO list.
    """
    tasks: Annotated[Optional[list[TaskExecutionItem]], replace] = Field(default=None)
    """
    The current tasks.
    """
    task_results: Annotated[list[DeepResearchSingleTaskResult], append] = Field(default=[])
    """
    Results of tasks executed by assistants.
    """
    intermediate_results: Annotated[list[DeepResearchIntermediateResult], append] = Field(default=[])
    """
    Intermediate reports.
    """
    previous_response_id: Optional[str] = Field(default=None)
    """
    The ID of the previous OpenAI Responses API response.
    """
    notebook_short_id: Optional[str] = Field(default=None)
    """
    The short ID of the notebook being used.
    """


class DeepResearchState(_SharedDeepResearchState):
    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])
    """
    Messages exposed to the user.
    """


class PartialDeepResearchState(_SharedDeepResearchState):
    messages: Sequence[AssistantMessageUnion] = Field(default=[])
    """
    Messages exposed to the user.
    """


class DeepResearchNodeName(StrEnum):
    START = START
    END = END
    ONBOARDING = "onboarding"
    NOTEBOOK_PLANNING = "notebook_planning"
    PLANNER = "planner"
    PLANNER_TOOLS = "planner_tools"
    TASK_EXECUTOR = "task_executor"
    REPORT = "report"
