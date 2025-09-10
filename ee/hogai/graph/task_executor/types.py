from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from ee.hogai.utils.types import AssistantMessageUnion, add_and_merge_messages
from ee.hogai.utils.types.base import BaseTaskExecutionState


class TaskExecutionState(BaseTaskExecutionState):
    """
    Full task execution state with messages.
    """

    messages: Annotated[Sequence[AssistantMessageUnion], add_and_merge_messages] = Field(default=[])


class PartialTaskExecutionState(BaseTaskExecutionState):
    """
    Partial task execution state for updates.
    """

    messages: Sequence[AssistantMessageUnion] = Field(default=[])
