import time
from typing import Literal
from uuid import uuid4

import openai
import structlog
import posthoganalytics
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.types import Send
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantMessageMetadata, HumanMessage

from posthog.event_usage import groups

from ee.hogai.chat_agent.memory.nodes import MemoryOnboardingNode
from ee.hogai.chat_agent.scope_gate.prompts import OUT_OF_SCOPE_REPLY, SCOPE_GATE_INPUT_TEMPLATE, SCOPE_GATE_PROMPT
from ee.hogai.core.node import AssistantNode
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.utils.feature_flags import has_scope_gate_feature_flag
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName

logger = structlog.get_logger(__name__)

SCOPE_GATE_MESSAGE_SOURCE = "scope_gate"
SCOPE_GATE_TIMEOUT_SECONDS = 2.0
PREVIOUS_ASSISTANT_MESSAGE_MAX_CHARS = 1000

ScopeVerdict = Literal["in_scope", "out_of_scope", "unsure"]
"""Classifier verdicts, plus "error" and "timeout" in the verdict event when the gate fails open."""


class ScopeClassification(BaseModel):
    verdict: ScopeVerdict = Field(description="Whether the user message is in scope for PostHog AI.")


class ScopeGateNode(AssistantNode):
    """
    Blocks messages that are clearly unrelated to the product before they reach the root agent.

    The node fails open: a disabled flag, a classifier error, a timeout, or an "unsure" verdict
    all let the message continue to the normal conversation flow.
    """

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if human_message is None:
            return None

        if not has_scope_gate_feature_flag(self._team, self._user):
            return None

        started_at = time.monotonic()
        verdict = await self._classify(state, human_message, config)
        blocked = verdict == "out_of_scope"
        self._capture_verdict(config, verdict, blocked, int((time.monotonic() - started_at) * 1000))

        if not blocked:
            return None
        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=OUT_OF_SCOPE_REPLY,
                    id=str(uuid4()),
                    meta=AssistantMessageMetadata(source=SCOPE_GATE_MESSAGE_SOURCE),
                )
            ]
        )

    async def arouter(self, state: AssistantState) -> AssistantNodeName | list[Send]:
        last_message = state.messages[-1] if state.messages else None
        if (
            isinstance(last_message, AssistantMessage)
            and last_message.meta is not None
            and last_message.meta.source == SCOPE_GATE_MESSAGE_SOURCE
        ):
            return AssistantNodeName.END

        memory_onboarding_should_run = await MemoryOnboardingNode(
            self._team, self._user
        ).should_run_onboarding_at_start(state)
        if memory_onboarding_should_run == "memory_onboarding":
            return [Send(AssistantNodeName.MEMORY_ONBOARDING, state)]
        return [
            Send(AssistantNodeName.ROOT, state),
            Send(AssistantNodeName.MEMORY_COLLECTOR, state),
        ]

    async def _classify(
        self, state: AssistantState, human_message: HumanMessage, config: RunnableConfig
    ) -> ScopeVerdict | Literal["error", "timeout"]:
        previous_assistant_message = find_last_message_of_type(state.messages, AssistantMessage)
        runnable = ChatPromptTemplate.from_messages(
            [("system", SCOPE_GATE_PROMPT), ("user", SCOPE_GATE_INPUT_TEMPLATE)]
        ) | self._build_model().with_structured_output(ScopeClassification, method="json_schema", include_raw=False)
        try:
            result = await runnable.ainvoke(
                {
                    "previous_assistant_message": (
                        previous_assistant_message.content[:PREVIOUS_ASSISTANT_MESSAGE_MAX_CHARS]
                        if previous_assistant_message
                        else ""
                    ),
                    "user_message": human_message.content,
                },
                config=config,
            )
        except openai.APITimeoutError:
            return "timeout"
        except Exception:
            logger.exception("scope_gate_classification_failed")
            return "error"
        if not isinstance(result, ScopeClassification):
            return "error"
        return result.verdict

    def _build_model(self) -> MaxChatOpenAI:
        return MaxChatOpenAI(
            model="gpt-5.6-luna",
            reasoning_effort="none",
            max_completion_tokens=50,
            max_retries=0,
            timeout=SCOPE_GATE_TIMEOUT_SECONDS,
            user=self._user,
            team=self._team,
            streaming=False,
            stream_usage=False,
            disable_streaming=True,
            billable=False,
            posthog_properties={"scope_gate": True},
        )

    def _capture_verdict(self, config: RunnableConfig, verdict: str, blocked: bool, latency_ms: int) -> None:
        configurable = config.get("configurable") or {}
        posthoganalytics.capture(
            distinct_id=str(self._user.distinct_id),
            event="max_scope_gate_verdict",
            properties={
                "verdict": verdict,
                "blocked": blocked,
                "latency_ms": latency_ms,
                "conversation_id": configurable.get("thread_id"),
                "$ai_trace_id": configurable.get("trace_id"),
            },
            groups=groups(None, self._team),
        )
