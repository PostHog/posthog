from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from ee.hogai.utils.types import AssistantMessageUnion, add_and_merge_messages
from ee.hogai.utils.types.base import (
    BaseTaskExecutionState,
    InsightArtifact,
    InsightCreationArtifact,
    InsightSearchArtifact,
    TaskExecutionResult,
)

DashboardSingleTaskResult = TaskExecutionResult[InsightArtifact]


class _SharedDashboardInsightSearchExecutionState(BaseTaskExecutionState[InsightSearchArtifact]):
    """
    Shared dashboard task execution state.
    """


class _SharedDashboardInsightCreationExecutionState(BaseTaskExecutionState[InsightCreationArtifact]):
    """
    Shared dashboard task execution state.
    """


class DashboardInsightSearchTaskExecutionState(_SharedDashboardInsightSearchExecutionState):
    """
    Full dashboard task execution state with messages.
    """

    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])


class PartialDashboardInsightSearchTaskExecutionState(_SharedDashboardInsightSearchExecutionState):
    """
    Partial dashboard task execution state for updates.
    """

    messages: Sequence[AssistantMessageUnion] = Field(default=[])


class PartialDashboardInsightCreationTaskExecutionState(_SharedDashboardInsightCreationExecutionState):
    """
    Partial dashboard task execution state for updates.
    """

    messages: Sequence[AssistantMessageUnion] = Field(default=[])


class DashboardInsightCreationTaskExecutionState(_SharedDashboardInsightCreationExecutionState):
    """
    Full dashboard task execution state with messages.
    """

    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])
