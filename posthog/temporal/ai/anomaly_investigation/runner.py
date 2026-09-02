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
import uuid
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import posthoganalytics
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import BaseModel, ValidationError

from posthog.models import Team, User
from posthog.temporal.ai.anomaly_investigation.prompts import SYSTEM_PROMPT
from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport, salvage_report
from posthog.temporal.ai.anomaly_investigation.tools import (
    FetchMetricSeriesArgs,
    InvestigationToolkit,
    RecentEventsArgs,
    RunHogQLQueryArgs,
    SimulateDetectorArgs,
    TopBreakdownArgs,
)

from products.alerts.backend.models.alert import AlertConfiguration

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 10
AGENT_MODEL = "claude-sonnet-5"
FINAL_REPORT_TOOL_NAME = "submit_investigation_report"
MAX_TOOL_RESULT_CHARS = 12_000  # ~3K tokens per call — keeps 10 calls well under the context limit.
# Sonnet 5 runs adaptive thinking by default, which counts against max_tokens —
# leave headroom so a thinking-heavy turn can't truncate the final report.
MAX_OUTPUT_TOKENS = 8192
# Per-request cap. The surrounding Temporal activity has its own (longer) deadline;
# this guards against a single stuck HTTP call hanging for the whole activity budget.
# Sized for adaptive-thinking turns, which run longer than plain tool-call turns.
LLM_REQUEST_TIMEOUT_SECONDS = 180.0


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

    final_report_tool = {
        "name": FINAL_REPORT_TOOL_NAME,
        "description": (
            "Submit the final anomaly investigation report. Use this instead of writing "
            "JSON as plain text when you have finished investigating."
        ),
        "input_schema": InvestigationReport.model_json_schema(),
    }

    # No temperature: Sonnet 5 rejects non-default sampling params with a 400.
    llm = MaxChatAnthropic(
        model=AGENT_MODEL,
        team=team,
        user=user,
        billable=True,
        inject_context=True,
        # One in-request retry absorbs a transient blip cheaply; the Temporal activity retry
        # (maximum_attempts=2) is the outer safety net. Keeping this low bounds the aggregate
        # LLM wall-clock so a run stays inside the activity's start_to_close deadline instead of
        # being killed mid-flight (which would skip the fallback report and re-run the whole agent).
        max_retries=1,
        max_tokens=MAX_OUTPUT_TOKENS,
        default_request_timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        posthog_properties={"ai_product": "alert_investigation_agent"},
    )
    llm_with_tools = llm.bind_tools(
        [
            *(
                {
                    "name": name,
                    "description": description,
                    "input_schema": schema.model_json_schema(),
                }
                for name, description, schema in tools_spec
            ),
            final_report_tool,
        ]
    )
    # Auto tool choice, not forced: Sonnet 5's default thinking mode only supports auto/none tool
    # choice, so forcing a specific tool returns a 400 and this finalize turn would fall through to
    # the generic fallback report. Binding *only* the final-report tool, plus the explicit "submit
    # now" nudge on the budget-exhausted turn, reliably elicits the call without forcing it; if the
    # model returns plain text instead, the text-JSON fallback in _parse_report still recovers it.
    llm_with_final_report = llm.bind_tools([final_report_tool])

    # Without a langchain CallbackHandler attached, MaxChatAnthropic's posthog_properties
    # never reach AI observability — langchain-anthropic itself doesn't emit $ai_* events.
    # Attach one here so every generation/span this agent makes shows up under
    # ai_product=alert_investigation_agent, matching the convention used by other
    # Temporal-driven agents (see llma_eval_reports/report_agent/graph.py).
    config: RunnableConfig = {"callbacks": _build_callbacks(team=team, alert=alert)}

    messages: list[Any] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=anomaly_context),
    ]

    tool_calls_used = 0
    # Every set of submit_investigation_report args seen, valid or not, oldest first.
    # When every parse path fails, salvage tries these newest-to-oldest so a corrective
    # retry that came back worse cannot clobber an earlier salvageable attempt.
    report_args_history: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_CALLS + 1):
        if heartbeat is not None:
            heartbeat()

        if tool_calls_used >= MAX_TOOL_CALLS:
            # Budget exhausted — no tool_use block in flight so we can send a plain
            # HumanMessage rather than stubbing pending tool_result pairs.
            messages.append(
                HumanMessage(
                    content=(
                        "Tool call budget exhausted. Submit the final InvestigationReport "
                        "now using whatever evidence you have. Pass hypotheses as a JSON "
                        "array of objects (title, rationale, evidence) and recommendations "
                        "as a JSON array of strings, never as serialized strings."
                    )
                )
            )
            # Production traces show this finalize turn is where Sonnet 5 mangles the
            # report args (leaked text-tool-call syntax, flattened hypothesis fields), so
            # give the model one corrective retry with the validation error before
            # falling back to salvage.
            for finalize_attempt in range(2):
                if heartbeat is not None:
                    heartbeat()
                try:
                    final = await llm_with_final_report.ainvoke(messages, config=config)
                except Exception as err:
                    # Swallow final-turn failures and return the best report we can rather
                    # than bouncing off Temporal retries — MaxChatAnthropic already exhausted
                    # its built-in retry budget, so another activity attempt is unlikely to help.
                    logger.warning("anomaly_investigation.llm_finalize_error", extra={"error": str(err)})
                    salvaged = _salvage_from_history(report_args_history) or _fallback_report(
                        f"LLM finalize call failed: {err}"
                    )
                    salvaged.tool_calls_used = tool_calls_used
                    return InvestigationRunResult(report=salvaged, tool_calls_used=tool_calls_used, model=AGENT_MODEL)
                messages.append(final)
                final_tool_calls = getattr(final, "tool_calls", None) or []
                report_args = _final_report_args(final_tool_calls)
                if report_args is None:
                    # Plain-text final answer; the text-JSON fallback below handles it.
                    break
                report_args_history.append(report_args)
                try:
                    forced_report = InvestigationReport.model_validate(report_args)
                except ValidationError as err:
                    error_summary = _validation_error_summary(err)
                    logger.warning(
                        "anomaly_investigation.report_validation_error",
                        extra={"error": error_summary, "finalize_attempt": finalize_attempt},
                    )
                    if finalize_attempt == 0:
                        # Answer every pending tool_use block or the retry request is
                        # rejected by the API for dangling tool calls.
                        for call in final_tool_calls:
                            messages.append(
                                ToolMessage(
                                    content=(
                                        f"Report rejected: {error_summary}. Call "
                                        f"{FINAL_REPORT_TOOL_NAME} again with corrected "
                                        "arguments: hypotheses must be a JSON array of "
                                        "objects with title, rationale and evidence keys; "
                                        "recommendations must be a JSON array of strings."
                                    ),
                                    tool_call_id=call.get("id") or call.get("tool_call_id") or "",
                                )
                            )
                        continue
                    break
                forced_report.tool_calls_used = tool_calls_used
                return InvestigationRunResult(report=forced_report, tool_calls_used=tool_calls_used, model=AGENT_MODEL)
            break

        try:
            response = await llm_with_tools.ainvoke(messages, config=config)
        except Exception as err:
            logger.warning("anomaly_investigation.llm_invoke_error", extra={"error": str(err)})
            return InvestigationRunResult(
                report=_fallback_report(f"LLM tool-calling loop failed: {err}"),
                tool_calls_used=tool_calls_used,
                model=AGENT_MODEL,
            )
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        report_error: str | None = None
        report_args = _final_report_args(tool_calls)
        if report_args is not None:
            report_args_history.append(report_args)
            try:
                structured_report = InvestigationReport.model_validate(report_args)
                structured_report.tool_calls_used = tool_calls_used
                return InvestigationRunResult(
                    report=structured_report, tool_calls_used=tool_calls_used, model=AGENT_MODEL
                )
            except ValidationError as err:
                report_error = _validation_error_summary(err)
                logger.warning("anomaly_investigation.report_validation_error", extra={"error": report_error})
        if not tool_calls:
            break

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            tool_call_id = call.get("id") or call.get("tool_call_id") or ""
            # Enforce the cap per-call, not just per-turn — a single assistant
            # response can emit several parallel tool_use blocks.
            if name == FINAL_REPORT_TOOL_NAME:
                content = (
                    f"Final report tool call was invalid ({report_error or 'missing required fields'}). "
                    "Submit it again: hypotheses must be a JSON array of objects with title, "
                    "rationale and evidence keys; recommendations must be a JSON array of strings."
                )
            elif tool_calls_used >= MAX_TOOL_CALLS:
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
            # the model's context window. Keep the first slice; if the
            # agent needs more it can issue a narrower query.
            if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_CHARS:
                content = content[:MAX_TOOL_RESULT_CHARS] + "\n[truncated — narrow the query for more]"
            messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))

    final_message = messages[-1]
    content = getattr(final_message, "content", "")
    report: InvestigationReport | None = _parse_report_text(content)
    if report is None:
        report = _salvage_from_history(report_args_history)
        if report is not None:
            logger.warning(
                "anomaly_investigation.report_salvaged",
                extra={"hypotheses_kept": len(report.hypotheses), "recommendations_kept": len(report.recommendations)},
            )
    if report is None:
        text = _stringify(content).strip()
        # Log only length, not content: the agent's final message can echo customer event
        # data, which must not land in centralized worker logs. The full output stays
        # available in the run's LLM analytics trace.
        logger.warning("anomaly_investigation.no_parsable_report", extra={"content_length": len(text)})
        report = _fallback_report(
            "Agent returned no final message."
            if not text
            else "Agent final message was not valid InvestigationReport JSON."
        )
    report.tool_calls_used = tool_calls_used
    return InvestigationRunResult(report=report, tool_calls_used=tool_calls_used, model=AGENT_MODEL)


def _build_callbacks(*, team: Team, alert: AlertConfiguration | None) -> list[BaseCallbackHandler]:
    callbacks: list[BaseCallbackHandler] = []
    client = posthoganalytics.default_client
    if client is None:
        return callbacks
    properties: dict[str, Any] = {
        "ai_product": "alert_investigation_agent",
        "team_id": team.id,
    }
    if alert is not None:
        properties["alert_id"] = str(alert.id)
    callbacks.append(
        CallbackHandler(
            client,
            distinct_id=str(team.id),
            trace_id=f"alert-investigation-{uuid.uuid4()}",
            properties=properties,
        )
    )
    return callbacks


def _final_report_args(tool_calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    for call in tool_calls:
        if call.get("name") == FINAL_REPORT_TOOL_NAME:
            return call.get("args") or {}
    return None


def _salvage_from_history(report_args_history: list[dict[str, Any]]) -> InvestigationReport | None:
    for args in reversed(report_args_history):
        report = salvage_report(args)
        if report is not None:
            return report
    return None


def _report_from_tool_calls(tool_calls: list[dict[str, Any]]) -> InvestigationReport | None:
    args = _final_report_args(tool_calls)
    if args is None:
        return None
    try:
        return InvestigationReport.model_validate(args)
    except ValidationError:
        return None


def _validation_error_summary(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(loc) for loc in detail['loc'])}: {detail['msg']}" for detail in err.errors()[:5])


def _parse_report_text(content: Any) -> InvestigationReport | None:
    text = _stringify(content).strip()
    # Try direct JSON; else find first/last brace.
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
            return InvestigationReport.model_validate(parsed)
        except (ValueError, TypeError, ValidationError):
            continue
    return None


def _parse_report(content: Any) -> InvestigationReport:
    report = _parse_report_text(content)
    if report is not None:
        return report
    text = _stringify(content).strip()
    if not text:
        return _fallback_report("Agent returned no final message.")
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
