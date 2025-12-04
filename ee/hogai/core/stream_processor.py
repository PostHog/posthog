from collections.abc import Coroutine
from typing import Any, Protocol, TypeVar

import structlog

from posthog.models import Team, User

from ee.hogai.utils.types.base import AssistantDispatcherEvent, AssistantResultUnion, LangGraphUpdateEvent

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=AssistantResultUnion)


class AssistantStreamProcessorProtocol(Protocol[T]):
    """Protocol defining the interface for assistant stream processors."""

    _team: Team
    """The team."""
    _user: User
    """The user."""
    _streamed_update_ids: set[str]
    """Tracks the IDs of messages that have been streamed."""

    def process(self, event: AssistantDispatcherEvent) -> Coroutine[Any, Any, list[T] | None]:
        """Process a dispatcher event and return a result or None."""
        ...

    def process_langgraph_update(self, event: LangGraphUpdateEvent) -> Coroutine[Any, Any, list[T] | None]:
        """Process a LangGraph update event and return a list of results or None."""
        ...

    def mark_id_as_streamed(self, message_id: str) -> None:
        """Mark a message ID as streamed."""
        self._streamed_update_ids.add(message_id)
