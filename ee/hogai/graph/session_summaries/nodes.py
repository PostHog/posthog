from typing import Literal
from uuid import uuid4
import time
from langchain_core.runnables import RunnableConfig
import structlog
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantToolCallMessage
from ee.hogai.graph.base import AssistantNode


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        session_id = state.summarization_session_id
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        try:
            # TODO: Replace with actual session summarization
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=f"In the session with id {session_id} I found the following insights: User tried to sign up, but encountered lots of API errors, so abandoned the flow.",
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                summarization_session_id=None,
                root_tool_call_id=None,
            )
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.exception(
                f"Session summarization failed",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "execution_time_ms": round(execution_time * 1000, 2),
                    "error": str(e),
                },
            )
            return self._create_error_response(
                "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different session id.",
                state.root_tool_call_id,
            )

    def router(self, _: AssistantState) -> Literal["end", "root"]:
        return "root"
