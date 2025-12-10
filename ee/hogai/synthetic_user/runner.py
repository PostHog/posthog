from typing import TYPE_CHECKING, Optional
from uuid import UUID

import structlog

from posthog.schema import AgentMode, HumanMessage

from posthog.models import Team, User

from ee.hogai.chat_agent.stream_processor import ChatAgentStreamProcessor
from ee.hogai.core.loop_graph.graph import AgentLoopGraph
from ee.hogai.core.runner import BaseAgentRunner
from ee.hogai.synthetic_user.mode_manager import SyntheticUserModeManager
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantGraphName

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ee.hogai.utils.types.composed import MaxNodeName


STREAMING_NODES: set["MaxNodeName"] = set()


VERBOSE_NODES: set["MaxNodeName"] = {
    AssistantNodeName.ROOT,
    AssistantNodeName.ROOT_TOOLS,
}


class SyntheticUserGraph(AgentLoopGraph):
    @property
    def mode_manager_class(self) -> type[SyntheticUserModeManager]:
        return SyntheticUserModeManager

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.SYNTHETIC_USER


class SyntheticUserRunner(BaseAgentRunner):
    _state: AssistantState | None
    _initial_state: AssistantState | PartialAssistantState | None

    def __init__(
        self,
        team: Team,
        *,
        message: HumanMessage | None = None,
        user: User,
        session_id: str | None = None,
        trace_id: Optional[str | UUID] = None,
    ):
        super().__init__(
            team,
            new_message=message,
            user=user,
            graph_class=SyntheticUserGraph,
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            session_id=session_id,
            is_new_conversation=False,
            trace_id=trace_id,
            use_checkpointer=False,
            stream_processor=ChatAgentStreamProcessor(
                verbose_nodes=VERBOSE_NODES,
                streaming_nodes=STREAMING_NODES,
                state_type=AssistantState,
                team=team,
                user=user,
            ),
        )

    def get_initial_state(self) -> AssistantState:
        if self._latest_message:
            new_state = AssistantState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
                query_generation_retry_count=0,
                graph_status=None,
                agent_mode=AgentMode.BROWSER_USE,
            )
            return new_state

        # When resuming, do not set the mode. It should start from the same mode as the previous generation.
        return AssistantState(messages=[])

    def get_resumed_state(self) -> PartialAssistantState:
        if not self._latest_message:
            return PartialAssistantState(messages=[])
        new_state = PartialAssistantState(
            messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
        )
        return new_state
