from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Optional

from langgraph.graph import END, START
from pydantic import BaseModel, Field

from posthog.schema import DeepResearchNotebook, PlanningStepStatus, TaskExecutionItem

from ee.hogai.utils.types import AssistantMessageUnion, add_and_merge_messages
from ee.hogai.utils.types.base import BaseStateWithMessages, BaseStateWithTasks, append, replace

NotebookInfo = DeepResearchNotebook


class DeepResearchTodo(BaseModel):
    """
    A TO-DO item in the research plan.
    """

    id: int
    description: str
    status: PlanningStepStatus
    priority: Literal["low", "medium", "high"]


class DeepResearchTask(TaskExecutionItem):
    """
    A task in the research plan.
    """

    task_type: Literal["create_insight"]


class DeepResearchIntermediateResult(BaseModel):
    """
    An intermediate result of a batch of work, that will be used to write the final report.
    """

    content: str
    artifact_ids: list[str] = Field(default=[])


class _SharedDeepResearchState(BaseStateWithMessages, BaseStateWithTasks):
    tasks: Annotated[Optional[list[DeepResearchTask]], replace] = Field(default=None)  # type: ignore[assignment]
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
    conversation_notebooks: Annotated[list[NotebookInfo], append] = Field(default=[])
    """
    All notebooks created across the entire conversation.
    """
    current_run_notebooks: Annotated[Optional[list[NotebookInfo]], replace] = Field(default=None)
    """
    Notebooks created in the current deep research run (reset on new run).
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
