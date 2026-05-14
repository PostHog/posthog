"""Followup-agent tool-calling loop.

Mirrors the structure of posthog/temporal/ai/anomaly_investigation/runner.py.
Fresh conversation primed with brief + events; bounded tool-call budget; final
message must be parseable as LiveInvestigationFindings.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from posthog.models import User
from posthog.temporal.ai.live_investigation.prompts import LIVE_INVESTIGATION_FOLLOWUP_PROMPT
from posthog.temporal.ai.live_investigation.schemas import (
    LiveInvestigationFindings,
    StartLiveInvestigationArgs,
)
from posthog.temporal.ai.live_investigation.tools import (
    GetEventDetailArgs,
    LiveInvestigationToolkit,
    RunHogQLQueryArgs,
)

from products.live_debugger.backend.models import LiveInvestigation, ProgramEvent

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 10
AGENT_MODEL = "claude-sonnet-4-6"
MAX_TOOL_RESULT_CHARS = 12_000
LLM_REQUEST_TIMEOUT_SECONDS = 90.0
EVENT_SAMPLE_LIMIT = 5


ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


def _render_brief(brief: dict[str, Any]) -> str:
    lines = ["# Brief from the calling agent\n"]
    if brief.get("hypothesis"):
        lines.append(f"**Hypothesis:** {brief['hypothesis']}")
    if brief.get("instrumentation_rationale"):
        lines.append(f"\n**Why this probe is here:** {brief['instrumentation_rationale']}")
    if brief.get("what_to_look_for"):
        lines.append("\n**What to look for:**")
        for item in brief["what_to_look_for"]:
            lines.append(f"- {item}")
    if brief.get("signal_summary"):
        lines.append(f"\n**Originating signal:** {brief['signal_summary']}")
    return "\n".join(lines)


def _render_parent_summary(parent: LiveInvestigation | None) -> str:
    if parent is None or not parent.findings:
        return ""
    findings = parent.findings
    return (
        f"# Parent investigation summary\n\n"
        f"This is a chained followup. Parent investigation {parent.id} concluded:\n"
        f"- **status**: {findings.get('status', '?')}\n"
        f"- **hypothesis outcome**: {findings.get('hypothesis_outcome', '?')}\n"
        f"- **summary**: {findings.get('summary', '')}\n"
        f"- **next step rationale**: {findings.get('next_step_rationale', '')}"
    )


def _summarize_events(events: list[ProgramEvent]) -> str:
    if not events:
        return "# Probe events\n\nNo probe events fired during the watch window."

    by_probe: dict[str, int] = {}
    by_function: dict[str, int] = {}
    for evt in events:
        if evt.probe_id:
            by_probe[evt.probe_id] = by_probe.get(evt.probe_id, 0) + 1
        key = f"{evt.filename or '?'}:{evt.function_name or '?'}"
        by_function[key] = by_function.get(key, 0) + 1

    sample = [evt.to_json() for evt in events[:EVENT_SAMPLE_LIMIT]]
    return json.dumps(
        {
            "section": "probe_events",
            "total_count": len(events),
            "by_probe": by_probe,
            "by_function": by_function,
            "sample_events": sample,
            "sample_truncated": len(events) > EVENT_SAMPLE_LIMIT,
        },
        default=str,
    )


async def run_followup_investigation(
    *,
    investigation: LiveInvestigation,
    events: list[ProgramEvent],
    user: User,
    heartbeat: Callable[[], None] | None = None,
) -> LiveInvestigationFindings:
    """Drive the followup agent loop and return parsed findings."""
    # Imported lazily — runner.py runs inside the activity, but the upstream activities
    # module imports this file at module load, and we don't want to pull `ee.hogai` in
    # at workflow-definition time.
    from ee.hogai.llm import MaxChatAnthropic

    toolkit = LiveInvestigationToolkit(
        team=investigation.team,
        investigation=investigation,
        events=events,
        heartbeat=heartbeat,
    )

    handlers: dict[str, ToolHandler] = {
        "get_event_detail": lambda raw: toolkit.get_event_detail(GetEventDetailArgs.model_validate(raw)),
        "run_hogql_query": lambda raw: toolkit.run_hogql_query(RunHogQLQueryArgs.model_validate(raw)),
        "start_live_investigation": lambda raw: toolkit.start_live_investigation(
            StartLiveInvestigationArgs.model_validate(raw)
        ),
    }

    tools_spec: list[tuple[str, str, type[BaseModel]]] = [
        (
            "get_event_detail",
            "Drill into a specific probe event by id to see its full locals and stack trace.",
            GetEventDetailArgs,
        ),
        (
            "run_hogql_query",
            "Run a read-only HogQL SELECT query to cross-check probe data against other PostHog data.",
            RunHogQLQueryArgs,
        ),
        (
            "start_live_investigation",
            "Chain a child investigation when this run's evidence is insufficient or the "
            "hypothesis was wrong. Returns the new investigation_id.",
            StartLiveInvestigationArgs,
        ),
    ]

    llm = MaxChatAnthropic(
        model=AGENT_MODEL,
        team=investigation.team,
        user=user,
        billable=True,
        inject_context=True,
        max_retries=2,
        temperature=0,
        default_request_timeout=LLM_REQUEST_TIMEOUT_SECONDS,
    )
    llm_with_tools = llm.bind_tools(
        [
            {"name": name, "description": description, "input_schema": schema.model_json_schema()}
            for name, description, schema in tools_spec
        ]
    )

    initial_human = "\n\n".join(
        section
        for section in (
            _render_brief(investigation.brief),
            _render_parent_summary(investigation.parent),
            _summarize_events(events),
        )
        if section
    )

    messages: list[Any] = [
        SystemMessage(content=LIVE_INVESTIGATION_FOLLOWUP_PROMPT),
        HumanMessage(content=initial_human),
    ]

    tool_calls_used = 0
    for _ in range(MAX_TOOL_CALLS + 1):
        if heartbeat is not None:
            heartbeat()

        if tool_calls_used >= MAX_TOOL_CALLS:
            messages.append(
                HumanMessage(
                    content=(
                        "Tool call budget exhausted. Emit the final LiveInvestigationFindings JSON "
                        "now using whatever evidence you have."
                    )
                )
            )
            if heartbeat is not None:
                heartbeat()
            try:
                final = await llm.ainvoke(messages)
            except Exception as err:
                logger.warning("live_investigation.llm_finalize_error", extra={"error": str(err)})
                return _fallback_findings(f"LLM finalize call failed: {err}")
            messages.append(final)
            break

        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as err:
            logger.warning("live_investigation.llm_invoke_error", extra={"error": str(err)})
            return _fallback_findings(f"LLM tool-calling loop failed: {err}")
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            tool_call_id = call.get("id") or call.get("tool_call_id") or ""
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
                        logger.warning(
                            "live_investigation.tool_error",
                            extra={"tool": name, "error": str(err)},
                        )
                        content = f"Tool {name} failed: {err}"
            if isinstance(content, str) and len(content) > MAX_TOOL_RESULT_CHARS:
                content = content[:MAX_TOOL_RESULT_CHARS] + "\n[truncated]"
            messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))

    final_message = messages[-1]
    return _parse_findings(getattr(final_message, "content", ""))


def _parse_findings(content: Any) -> LiveInvestigationFindings:
    text = _stringify(content).strip()
    if not text:
        return _fallback_findings("Agent returned no final message.")
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
            return LiveInvestigationFindings.model_validate(parsed)
        except (ValueError, TypeError, ValidationError):
            continue
    return _fallback_findings("Agent final message was not valid LiveInvestigationFindings JSON.")


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


def _fallback_findings(reason: str) -> LiveInvestigationFindings:
    return LiveInvestigationFindings(
        status="gave_up",
        summary=reason[:500],
        confidence=0.0,
        hypothesis_outcome="inconclusive",
    )
