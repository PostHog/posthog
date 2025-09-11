from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Optional

from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.schema import PlanningStepStatus

from ee.hogai.utils.types import AssistantMessageUnion, add_and_merge_messages
from ee.hogai.utils.types.base import (
    BaseTaskExecutionState,
    InsightCreationArtifact,
    TaskExecutionResult,
    append,
    replace,
)


class DeepResearchTodo(BaseModel):
    """
    A TO-DO item in the research plan.
    """

    id: int
    description: str
    status: PlanningStepStatus
    priority: Literal["low", "medium", "high"]


DeepResearchSingleTaskResult = TaskExecutionResult[InsightCreationArtifact]


class DeepResearchIntermediateResult(BaseModel):
    """
    An intermediate result of a batch of work, that will be used to write the final report.
    """

    content: str
    artifact_ids: list[str] = Field(default=[])


class _SharedDeepResearchState(BaseTaskExecutionState[InsightCreationArtifact]):
    todos: Annotated[Optional[list[DeepResearchTodo]], replace] = Field(default=None)
    """
    The current TO-DO list.
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
