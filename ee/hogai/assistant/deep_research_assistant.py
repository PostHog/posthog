from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from posthog.schema import (
    AssistantMessage,
    HumanMessage,
    MaxBillingContext,
    ReasoningMessage,
    TaskExecutionMessage,
    VisualizationMessage,
)

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.graph import DeepResearchAssistantGraph
from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.types import AssistantMode, AssistantOutput
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models import Conversation


class DeepResearchAssistant(BaseAssistant):
    _state: DeepResearchState | None
    _initial_state: DeepResearchState | PartialDeepResearchState | None

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: HumanMessage | None = None,
        user: User,
        session_id: str | None = None,
        contextual_tools: dict[str, Any] | None = None,
        is_new_conversation: bool = False,
        trace_id: str | UUID | None = None,
        billing_context: MaxBillingContext | None = None,
        initial_state: DeepResearchState | PartialDeepResearchState | None = None,
    ):
        super().__init__(
            team,
            conversation,
            new_message=new_message,
            user=user,
            graph=DeepResearchAssistantGraph(team, user).compile_full_graph(),
            state_type=DeepResearchState,
            partial_state_type=PartialDeepResearchState,
            mode=AssistantMode.DEEP_RESEARCH,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,
        )

    @property
    def VISUALIZATION_NODES(self) -> dict[MaxNodeName, type[BaseAssistantNode]]:
        return {}

    @property
    def STREAMING_NODES(self) -> set[MaxNodeName]:
        return {
            DeepResearchNodeName.ONBOARDING,
            DeepResearchNodeName.PLANNER,
            DeepResearchNodeName.TASK_EXECUTOR,
        }

    @property
    def VERBOSE_NODES(self) -> set[MaxNodeName]:
        return self.STREAMING_NODES | {
            DeepResearchNodeName.PLANNER_TOOLS,
            DeepResearchNodeName.TASK_EXECUTOR,
        }

    @property
    def THINKING_NODES(self) -> set[MaxNodeName]:
        return {
            DeepResearchNodeName.ONBOARDING,
            DeepResearchNodeName.NOTEBOOK_PLANNING,
            DeepResearchNodeName.PLANNER,
            DeepResearchNodeName.REPORT,
        }

    def _should_persist_stream_message(self, message: BaseModel, node_name: MaxNodeName) -> bool:
        """
        Only persist discrete, low-frequency stream events.
        Avoid persisting chunked AssistantMessage text to reduce DB write volume.
        Persisting reasoning and task execution messages from deep research.
        """
        if isinstance(node_name, DeepResearchNodeName):
            if isinstance(message, ReasoningMessage):
                return True
            if isinstance(message, TaskExecutionMessage):
                return True
        return False

    def _should_persist_commentary_message(self, node_name: MaxNodeName) -> bool:
        """Persist complete commentary lines emitted by planner/task executor tools."""
        if isinstance(node_name, DeepResearchNodeName):
            return node_name in {
                DeepResearchNodeName.PLANNER,
                DeepResearchNodeName.TASK_EXECUTOR,
            }
        return False

    def get_initial_state(self) -> DeepResearchState:
        if self._latest_message:
            return DeepResearchState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
                graph_status=None,
                notebook_short_id=None,
            )
        else:
            return DeepResearchState(messages=[])

    def get_resumed_state(self) -> PartialDeepResearchState:
        if not self._latest_message:
            return PartialDeepResearchState(messages=[])
        return PartialDeepResearchState(messages=[self._latest_message], graph_status="resumed")

    async def astream(
        self,
        stream_message_chunks: bool = True,
        stream_subgraphs: bool = True,
        stream_first_message: bool = True,
        stream_only_assistant_messages: bool = False,
    ) -> AsyncGenerator[AssistantOutput, None]:
        last_ai_message: AssistantMessage | None = None
        async for stream_event in super().astream(
            stream_message_chunks, stream_subgraphs, stream_first_message, stream_only_assistant_messages
        ):
            _, message = stream_event
            if isinstance(message, VisualizationMessage):
                # We don't want to send single visualization messages to the client in deep research mode
                continue
            if isinstance(message, AssistantMessage):
                last_ai_message = message
            yield stream_event

        await self._report_conversation_state(
            "deep research",
            {
                "prompt": self._latest_message.content if self._latest_message else None,
                "output": last_ai_message,
                "is_new_conversation": self._is_new_conversation,
            },
        )
