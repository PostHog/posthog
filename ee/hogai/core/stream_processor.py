from typing import Protocol

import structlog

from ee.hogai.utils.types.base import AssistantDispatcherEvent, AssistantResultUnion, LangGraphUpdateEvent

logger = structlog.get_logger(__name__)


class AssistantStreamProcessorProtocol(Protocol):
    """Protocol defining the interface for assistant stream processors."""

    _streamed_update_ids: set[str]
    """Tracks the IDs of messages that have been streamed."""

    def process(self, event: AssistantDispatcherEvent) -> list[AssistantResultUnion] | None:
        """Process a dispatcher event and return a result or None."""
        ...

    def process_langgraph_update(self, event: LangGraphUpdateEvent) -> list[AssistantResultUnion] | None:
        """Process a LangGraph update event and return a list of results or None."""
        ...

    def mark_id_as_streamed(self, message_id: str) -> None:
        """Mark a message ID as streamed."""
        self._streamed_update_ids.add(message_id)
