"""Single-pass anomaly investigation agent loop.

Kept small on purpose: we don't need LangGraph's conditional routing or the
streaming machinery from Max — just a tool-calling loop that terminates with a
structured report.

Budget: at most MAX_TOOL_CALLS tool invocations. After that the agent is told
to finalize with what it has. The loop exits either on a final assistant
message with no tool calls, or on budget exhaustion.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from posthog.models import Team, User
from posthog.models.alert import AlertConfiguration
from posthog.temporal.ai.anomaly_investigation.prompts import SYSTEM_PROMPT
from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport
from posthog.temporal.ai.anomaly_investigation.tools import (
    FetchMetricSeriesArgs,
    InvestigationToolkit,
    RecentEventsArgs,
    RunHogQLQueryArgs,
    SimulateDetectorArgs,
    TopBreakdownArgs,
)

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 10
AGENT_MODEL = "claude-sonnet-4-6"
MAX_TOOL_RESULT_CHARS = 12_000  # ~3K tokens per call — keeps 10 calls well under the context limit.
# Per-request cap. The surrounding Temporal activity has its own (longer) deadline;
# this guards against a single stuck HTTP call hanging for the whole activity budget.
LLM_REQUEST_TIMEOUT_SECONDS = 90.0


ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass
class InvestigationRunResult:
    report: InvestigationReport
    tool_calls_used: int
    model: str


async def run_investigation(
    *,
    team: Team,
    user: User,
    anomaly_context: Any,  # str or list[{type, ...}] LangChain content blocks
    alert: AlertConfiguration | None = None,
    heartbeat: Callable[[], None] | None = None,
) -> InvestigationRunResult:
    """Drive the agent loop to completion and return the structured report.

    ``anomaly_context`` accepts either a plain string or a list of content blocks
    (text + image for multimodal input). ``alert`` gives metric-specific tools a
    handle on the insight and detector_config. ``heartbeat`` is invoked once per
    iteration so the enclosing Temporal activity stays alive during long LLM calls.
    """
    # Imported here so the workflow module does not require the ee package at import time
    # (Temporal workflow sandbox restrictions).
    from ee.hogai.llm import MaxChatAnthropic

    toolkit = InvestigationToolkit(team=team, alert=alert)
    handlers: dict[str, ToolHandler] = {
        "run_hogql_query": lambda raw: toolkit.run_hogql_query(RunHogQLQueryArgs.model_validate(raw)),
        "top_breakdowns": lambda raw: toolkit.top_breakdowns(TopBreakdownArgs.model_validate(raw)),
        "recent_events": lambda raw: toolkit.recent_events(RecentEventsArgs.model_validate(raw)),
        "fetch_metric_series": lambda raw: toolkit.fetch_metric_series(FetchMetricSeriesArgs.model_validate(raw)),
        "simulate_detector": lambda raw: toolkit.simulate_detector(SimulateDetectorArgs.model_validate(raw)),
    }

    tools_spec: list[tuple[str, str, type[BaseModel]]] = [
        (
            "run_hogql_query",
            "Run a read-only HogQL SELECT query against the team's event data. Use sparingly and keep queries narrow.",
            RunHogQLQueryArgs,
        ),
        (
            "top_breakdowns",
            "Fetch the top values of a property for an event in a time window.",
            TopBreakdownArgs,
        ),
        (
            "recent_events",
            "Fetch a handful of recent events in a time window, optionally filtered by event name.",
            RecentEventsArgs,
        ),
        (
            "fetch_metric_series",
            (
                "Return the alert's own insight time series (labels + values) at its configured "
                "interval. Prefer this over run_hogql_query when you need the exact metric the "
                "detector was scoring."
            ),
            FetchMetricSeriesArgs,
        ),
        (
            "simulate_detector",
            (
                "Run the alert's detector over a historical window and return the scored points "
                "plus any timestamps the detector would have flagged. Use to check whether the "
                "current fire is an isolated spike or part of a recurring pattern."
            ),
            SimulateDetectorArgs,
        ),
    ]

    llm = MaxChatAnthropic(
        model=AGENT_MODEL,
        team=team,
        user=user,
        billable=True,
        inject_context=True,
        max_retries=2,
        temperature=0,
        default_request_timeout=LLM_REQUEST_TIMEOUT_SECONDS,
    )
    llm_with_tools = llm.bind_tools(
        [
            {
                "name": name,
                "description": description,
                "input_schema": schema.model_json_schema(),
            }
            for name, description, schema in tools_spec
        ]
    )

    messages: list[Any] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=anomaly_context),
    ]

    tool_calls_used = 0

    for _ in range(MAX_TOOL_CALLS + 1):
        if heartbeat is not None:
            heartbeat()

        if tool_calls_used >= MAX_TOOL_CALLS:
            # Budget exhausted — no tool_use block in flight so we can send a plain
            # HumanMessage rather than stubbing pending tool_result pairs.
            messages.append(
                HumanMessage(
                    content=(
                        "Tool call budget exhausted. Emit the final InvestigationReport JSON "
                        "now using whatever evidence you have."
                    )
                )
            )
            if heartbeat is not None:
                heartbeat()
            try:
                final = await llm.ainvoke(messages)
            except Exception as err:
                # Swallow final-turn failures and return an inconclusive report rather than
                # bouncing off Temporal retries — MaxChatAnthropic already exhausted its
                # built-in retry budget, so another activity attempt is unlikely to help.
                logger.warning("anomaly_investigation.llm_finalize_error", extra={"error": str(err)})
                return InvestigationRunResult(
                    report=_fallback_report(f"LLM finalize call failed: {err}"),
                    tool_calls_used=tool_calls_used,
                    model=AGENT_MODEL,
                )
            messages.append(final)
            break

        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as err:
            logger.warning("anomaly_investigation.llm_invoke_error", extra={"error": str(err)})
            return InvestigationRunResult(
                report=_fallback_report(f"LLM tool-calling loop failed: {err}"),
                tool_calls_used=tool_calls_used,
                model=AGENT_MODEL,
            )
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            tool_call_id = call.get("id") or call.get("tool_call_id") or ""
            # Enforce the cap per-call, not just per-turn — a single assistant
            # response can emit several parallel tool_use blocks.
            if tool_calls_used >= MAX_TOOL_CALLS:
                content = "[skipped — tool call budget exhausted]"
            else:
                tool_calls_used += 1
                handler = handlers.get(name)
                if handler is None:
                    content = f"Unknown tool: {name}"
                else:
                    try:
                        content = await handler(args)
                    except Exception as err:
                        logger.warning("anomaly_investigation.tool_error", extra={"tool": name, "error": str(err)})
                        content = f"Tool {name} failed: {err}"
            # Guard against runaway tool responses pushing the conversation past
            # Anthropic's 200K-token context window. Keep the first slice; if the
            # agent needs more it can issue a narrower query.
            if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_CHARS:
                content = content[:MAX_TOOL_RESULT_CHARS] + "\n[truncated — narrow the query for more]"
            messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))

    final_message = messages[-1]
    report = _parse_report(getattr(final_message, "content", ""))
    report.tool_calls_used = tool_calls_used
    return InvestigationRunResult(report=report, tool_calls_used=tool_calls_used, model=AGENT_MODEL)


def _parse_report(content: Any) -> InvestigationReport:
    text = _stringify(content).strip()
    if not text:
        return _fallback_report("Agent returned no final message.")
    # Try direct JSON; else find first/last brace.
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
            return InvestigationReport.model_validate(parsed)
        except (ValueError, TypeError, ValidationError):
            continue
    return _fallback_report("Agent final message was not valid InvestigationReport JSON.")


def _json_candidates(text: str) -> list[str]:
    candidates: list[str] = [text]
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    return candidates


def _stringify(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                chunks.append(item["text"])
            elif isinstance(item, str):
                chunks.append(item)
        return "".join(chunks)
    return str(content)


def _fallback_report(reason: str) -> InvestigationReport:
    return InvestigationReport(
        verdict="inconclusive",
        summary=reason,
        hypotheses=[],
        recommendations=["Review the insight manually — the agent could not produce a structured report."],
    )
