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

from posthog.dataclasses import frozen
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


@frozen
class _ToolCallOutcome:
    result: InvestigationRunResult | None
    should_stop: bool


def _result(report: InvestigationReport, tool_calls_used: int) -> InvestigationRunResult:
    report.tool_calls_used = tool_calls_used
    return InvestigationRunResult(report=report, tool_calls_used=tool_calls_used, model=AGENT_MODEL)


def _validation_error_summary(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(loc) for loc in detail['loc'])}: {detail['msg']}" for detail in err.errors()[:5])


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


def _add_report_correction_messages(messages: list[Any], tool_calls: list[dict[str, Any]], error_summary: str) -> None:
    for call in tool_calls:
        messages.append(
            ToolMessage(
                content=(
                    f"Report rejected: {error_summary}. Call {FINAL_REPORT_TOOL_NAME} again with corrected "
                    "arguments: hypotheses must be a JSON array of objects with title, rationale and evidence "
                    "keys; recommendations must be a JSON array of strings."
                ),
                tool_call_id=call.get("id") or call.get("tool_call_id") or "",
            )
        )


def _fallback_report(reason: str) -> InvestigationReport:
    return InvestigationReport(
        verdict="inconclusive",
        summary=reason,
        hypotheses=[],
        recommendations=["Review the insight manually — the agent could not produce a structured report."],
    )


class _InvestigationRunner:
    """Owns the mutable state for one investigation loop: messages, tool budget, and report history."""

    def __init__(
        self,
        *,
        llm_with_tools: Any,
        llm_with_final_report: Any,
        handlers: dict[str, ToolHandler],
        config: RunnableConfig,
        heartbeat: Callable[[], None] | None,
    ) -> None:
        self._llm_with_tools = llm_with_tools
        self._llm_with_final_report = llm_with_final_report
        self._handlers = handlers
        self._config = config
        self._heartbeat = heartbeat
        self.messages: list[Any] = []
        self.tool_calls_used = 0
        # Every set of submit_investigation_report args seen, valid or not, oldest first.
        # When every parse path fails, salvage tries these newest-to-oldest so a corrective
        # retry that came back worse cannot clobber an earlier salvageable attempt.
        self.report_args_history: list[dict[str, Any]] = []

    def _tick_heartbeat(self) -> None:
        if self._heartbeat is not None:
            self._heartbeat()

    async def run(self, *, anomaly_context: Any) -> InvestigationRunResult:
        self.messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=anomaly_context),
        ]
        for _ in range(MAX_TOOL_CALLS + 1):
            self._tick_heartbeat()

            if self.tool_calls_used >= MAX_TOOL_CALLS:
                result = await self._finalize_after_tool_budget()
                if result is not None:
                    return result
                break

            try:
                response = await self._llm_with_tools.ainvoke(self.messages, config=self._config)
            except Exception as err:
                logger.warning("anomaly_investigation.llm_invoke_error", extra={"error": str(err)})
                return InvestigationRunResult(
                    report=_fallback_report(f"LLM tool-calling loop failed: {err}"),
                    tool_calls_used=self.tool_calls_used,
                    model=AGENT_MODEL,
                )
            self.messages.append(response)

            tool_calls = getattr(response, "tool_calls", None) or []
            outcome = await self._handle_tool_calls(tool_calls)
            if outcome.result is not None:
                return outcome.result
            if outcome.should_stop:
                break

        return self._finish_investigation()

    async def _finalize_after_tool_budget(self) -> InvestigationRunResult | None:
        # _run_tool_calls answers every tool_use block before the loop re-reads the budget,
        # so no tool call is in flight and a plain HumanMessage is valid here. The model API
        # rejects a request that still holds an unanswered tool_use block.
        self.messages.append(
            HumanMessage(
                content=(
                    "Tool call budget exhausted. Submit the final InvestigationReport "
                    "now using whatever evidence you have. Pass hypotheses as a JSON "
                    "array of objects (title, rationale, evidence) and recommendations "
                    "as a JSON array of strings, never as serialized strings."
                )
            )
        )
        # Sonnet 5 can corrupt nested report fields on this final turn. Let it correct them once.
        for finalize_attempt in range(2):
            self._tick_heartbeat()
            try:
                final = await self._llm_with_final_report.ainvoke(self.messages, config=self._config)
            except Exception as err:
                # Swallow final-turn failures and return the best report we can rather
                # than bouncing off Temporal retries — MaxChatAnthropic already exhausted
                # its built-in retry budget, so another activity attempt is unlikely to help.
                logger.warning("anomaly_investigation.llm_finalize_error", extra={"error": str(err)})
                report = _salvage_from_history(self.report_args_history) or _fallback_report(
                    f"LLM finalize call failed: {err}"
                )
                return _result(report, self.tool_calls_used)
            self.messages.append(final)
            final_tool_calls = getattr(final, "tool_calls", None) or []
            report_args = _final_report_args(final_tool_calls)
            if report_args is None:
                # Plain-text final answer. Stop the finalize retries so _finish_investigation
                # parses the text with the JSON fallback.
                return None
            self.report_args_history.append(report_args)
            try:
                return _result(InvestigationReport.model_validate(report_args), self.tool_calls_used)
            except ValidationError as err:
                error_summary = _validation_error_summary(err)
                logger.warning(
                    "anomaly_investigation.report_validation_error",
                    extra={"error": error_summary, "finalize_attempt": finalize_attempt},
                )
                if finalize_attempt == 0:
                    _add_report_correction_messages(self.messages, final_tool_calls, error_summary)
                    continue
        return None

    async def _handle_tool_calls(self, tool_calls: list[dict[str, Any]]) -> _ToolCallOutcome:
        report_error: str | None = None
        report_args = _final_report_args(tool_calls)
        if report_args is not None:
            self.report_args_history.append(report_args)
            try:
                return _ToolCallOutcome(
                    result=_result(InvestigationReport.model_validate(report_args), self.tool_calls_used),
                    should_stop=False,
                )
            except ValidationError as err:
                report_error = _validation_error_summary(err)
                logger.warning("anomaly_investigation.report_validation_error", extra={"error": report_error})
        if not tool_calls:
            return _ToolCallOutcome(result=None, should_stop=True)
        return await self._run_tool_calls(tool_calls=tool_calls, report_error=report_error)

    async def _run_tool_calls(self, *, tool_calls: list[dict[str, Any]], report_error: str | None) -> _ToolCallOutcome:
        for call in tool_calls:
            content = await self._run_tool_call(call=call, report_error=report_error)
            if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_CHARS:
                content = content[:MAX_TOOL_RESULT_CHARS] + "\n[truncated — narrow the query for more]"
            self.messages.append(
                ToolMessage(content=content, tool_call_id=call.get("id") or call.get("tool_call_id") or "")
            )
        return _ToolCallOutcome(result=None, should_stop=False)

    async def _run_tool_call(self, *, call: dict[str, Any], report_error: str | None) -> str:
        name = call.get("name")
        if name == FINAL_REPORT_TOOL_NAME:
            return (
                f"Final report tool call was invalid ({report_error or 'missing required fields'}). "
                "Submit it again: hypotheses must be a JSON array of objects with title, "
                "rationale and evidence keys; recommendations must be a JSON array of strings."
            )
        if self.tool_calls_used >= MAX_TOOL_CALLS:
            return "[skipped — tool call budget exhausted]"
        self.tool_calls_used += 1
        handler = self._handlers.get(name) if isinstance(name, str) else None
        if handler is None:
            return f"Unknown tool: {name}"
        try:
            return await handler(call.get("args") or {})
        except Exception as err:
            logger.warning("anomaly_investigation.tool_error", extra={"tool": name, "error": str(err)})
            return f"Tool {name} failed: {err}"

    def _finish_investigation(self) -> InvestigationRunResult:
        content = getattr(self.messages[-1], "content", "")
        report = _parse_report_text(content)
        if report is None:
            report = _salvage_from_history(self.report_args_history)
            if report is not None:
                logger.warning(
                    "anomaly_investigation.report_salvaged",
                    extra={
                        "hypotheses_kept": len(report.hypotheses),
                        "recommendations_kept": len(report.recommendations),
                    },
                )
        if report is None:
            text = _stringify(content).strip()
            # Log the length only because the message can contain tenant event data.
            logger.warning("anomaly_investigation.no_parsable_report", extra={"content_length": len(text)})
            report = _fallback_report(
                "Agent returned no final message."
                if not text
                else "Agent final message was not valid InvestigationReport JSON."
            )
        return _result(report, self.tool_calls_used)


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

    runner = _InvestigationRunner(
        llm_with_tools=llm_with_tools,
        llm_with_final_report=llm_with_final_report,
        handlers=handlers,
        config=config,
        heartbeat=heartbeat,
    )
    return await runner.run(anomaly_context=anomaly_context)


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


def _report_from_tool_calls(tool_calls: list[dict[str, Any]]) -> InvestigationReport | None:
    args = _final_report_args(tool_calls)
    if args is None:
        return None
    try:
        return InvestigationReport.model_validate(args)
    except ValidationError:
        return None


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
