from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from ee.hogai.utils.types import AssistantMessageUnion, add_and_merge_messages
from ee.hogai.utils.types.base import BaseTaskExecutionState, InsightArtifact, TaskExecutionResult

DashboardSingleTaskResult = TaskExecutionResult[InsightArtifact]


class _SharedDashboardTaskExecutionState(BaseTaskExecutionState):
    """
    Shared dashboard task execution state.
    """


class DashboardTaskExecutionState(_SharedDashboardTaskExecutionState):
    """
    Full dashboard task execution state with messages.
    """

    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])


class PartialDashboardTaskExecutionState(_SharedDashboardTaskExecutionState):
    """
    Partial dashboard task execution state for updates.
    """

    messages: Sequence[AssistantMessageUnion] = Field(default=[])
