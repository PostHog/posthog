"""Synthetic AI traffic in the three shapes the suggestions research checked, for local runs and tests.

Every product, person, id and sentence here is invented. The shapes are written from the properties
each one has to exercise:

- A code review agent. Each review runs four lenses in one session, and each lens returns JSON findings
  with a priority. The security lenses mark far more findings P0 or P1 than the others.
- A chat agent that routes almost every action through one dispatcher tool, polls a status tool with the
  same arguments, and explores docs with different queries. About 1 in 60 turns ends on a failed call that
  nothing retries. Approval pauses raise an interrupt error that is not a failure, and some failed searches
  succeed on retry. Answers link to docs and name versions.
- A scout agent that queries data and files a finding, plus an enabled judge whose filter names a product
  value the scouts no longer send.
"""

import json
import uuid
import random
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL
from posthog.models.team import Team

from products.ai_observability.backend.models.evaluations import Evaluation

REVIEWS_PER_WEEK = 70
CHAT_SESSIONS_PER_WEEK = 260
SCOUT_RUNS_PER_WEEK = 220
UNRECOVERED_EVERY_N_TURNS = 25
DEAD_JUDGE_NAME = "Scout findings are grounded"

_PRIORITY_WEIGHTS = {
    "security": [0.10, 0.25, 0.40, 0.25],
    "performance": [0.0, 0.02, 0.48, 0.50],
    "correctness": [0.02, 0.06, 0.52, 0.40],
}
_FINDINGS = {
    "security": [
        "User-supplied file name reaches open() without validation",
        "Session token compared with == instead of a constant-time check",
        "Debug route stays reachable when the feature toggle is off",
        "Webhook signature is checked after the payload is parsed",
        "Export endpoint skips the project permission check",
    ],
    "performance": [
        "Query inside the loop runs once per invoice line",
        "Whole table is loaded to count rows",
        "Cache key ignores the locale, so hits are rare",
        "Retry loop has no backoff",
    ],
    "correctness": [
        "Discount is applied twice when the coupon is reused",
        "Time zone is dropped when the due date is parsed",
        "Empty list returns the first page instead of nothing",
        "Rounding happens before the currency conversion",
    ],
}
_FILES = ["billing/invoice.py", "notes/export.ts", "auth/session.go", "api/webhooks.py", "sync/worker.rs"]
# Each question has the answer that fits it, so a mismatch never reads as a failure the seed did not plan.
_QUESTIONS = {
    "How do I export my notes to PDF?": "You can export from the note menu. Steps are at https://example.com/docs/export, and PDF export needs app version v2.31.4 or later.",
    "Move every note tagged draft into the archive folder.": "Done. I moved 12 notes into the archive folder.",
    "Why did my shared notebook stop syncing?": "Sync stopped because the device token expired. Sign in again on that device.",
    "Can you rename the Q3 planning folder to Q4 planning?": "The folder is renamed. Shared links keep working.",
    "Set a reminder on the onboarding checklist for Friday.": "Reminder set for Friday at 9:00.",
    "Which plan includes version history?": "Version history is on the Team plan.",
}
_ACTIONS = ["move_note", "rename_folder", "set_reminder", "tag_note", "share_note", "list_notes"]
_SCOUT_TOPICS = ["checkout errors", "signup drop", "slow search", "export failures", "billing retries"]


@frozen
class DemoEvent:
    event: str
    uuid: str
    distinct_id: str
    timestamp: datetime
    properties: dict[str, Any]


class _Builder:
    def __init__(self, now: datetime, rng: random.Random) -> None:
        self.now = now
        self.rng = rng
        self.events: list[DemoEvent] = []

    def uid(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def start_time(self) -> datetime:
        return self.now - timedelta(hours=1) - timedelta(seconds=self.rng.uniform(0, 7 * 24 * 3600 - 7200))

    def add(self, event: str, distinct_id: str, timestamp: datetime, properties: dict[str, Any]) -> None:
        self.events.append(
            DemoEvent(event=event, uuid=self.uid(), distinct_id=distinct_id, timestamp=timestamp, properties=properties)
        )

    def generation(
        self,
        distinct_id: str,
        timestamp: datetime,
        trace: dict[str, Any],
        messages: list[dict[str, Any]],
        output: dict[str, Any],
        **extra: Any,
    ) -> None:
        tool_calls = output.get("tool_calls") or []
        input_tokens = sum(len(json.dumps(message)) for message in messages) // 4 + 50
        output_tokens = len(json.dumps(output)) // 4 + 5
        properties = {
            **trace,
            "$ai_model": "example-model-mini",
            "$ai_provider": "openai",
            "$ai_input": messages,
            "$ai_output_choices": [output],
            "$ai_input_tokens": input_tokens,
            "$ai_output_tokens": output_tokens,
            "$ai_total_cost_usd": round(input_tokens * 0.25e-6 + output_tokens * 2e-6, 8),
            "$ai_latency": round(self.rng.uniform(0.4, 4.0), 2),
            **extra,
        }
        if tool_calls:
            properties["$ai_tools_called"] = ",".join(call["function"]["name"] for call in tool_calls)
            properties["$ai_tool_call_count"] = len(tool_calls)
        self.add("$ai_generation", distinct_id, timestamp, properties)

    def tool_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function",
            "id": f"call_{self.uid()[:12]}",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }

    def span(
        self, distinct_id: str, timestamp: datetime, trace: dict[str, Any], name: str, error: str | None = None
    ) -> None:
        properties = {**trace, "$ai_span_name": name, "$ai_span_id": self.uid()}
        if error:
            properties |= {"$ai_is_error": True, "$ai_error": error}
        self.add("$ai_span", distinct_id, timestamp, properties)


def _code_reviews(builder: _Builder, count: int) -> None:
    rng = builder.rng
    for review in range(count):
        session_id = f"review-{builder.uid()}"
        started = builder.start_time()
        file = rng.choice(_FILES)
        diff = f"diff --git a/{file} b/{file}\n@@ -10,6 +10,9 @@\n+    handle(request.args['name'])\n"
        for offset, lens in enumerate(("security-1", "security-2", "performance", "correctness")):
            trace = {
                "$ai_trace_id": builder.uid(),
                "$ai_session_id": session_id,
                "ai_product": "code_review",
                "review_lens": lens,
            }
            at = started + timedelta(seconds=offset * 40)
            system = {"role": "system", "content": f"You review pull requests through the {lens.split('-')[0]} lens."}
            user = {"role": "user", "content": f"Review this change to {file}:\n{diff}"}
            read = builder.tool_call("read_file", {"path": file, "review": review})
            builder.generation(
                f"reviewer-{review % 9}",
                at,
                trace,
                [system, user],
                {"role": "assistant", "content": "", "tool_calls": [read]},
            )
            tool_result = {"role": "tool", "tool_call_id": read["id"], "content": f"contents of {file}"}
            weights = _PRIORITY_WEIGHTS[lens.split("-")[0]]
            findings = [
                {
                    "title": rng.choice(_FINDINGS[lens.split("-")[0]]),
                    "file": file,
                    "priority": rng.choices(["P0", "P1", "P2", "P3"], weights=weights)[0],
                }
                for _ in range(rng.randint(2, 5))
            ]
            builder.generation(
                f"reviewer-{review % 9}",
                at + timedelta(seconds=15),
                trace,
                [system, user, {"role": "assistant", "content": "", "tool_calls": [read]}, tool_result],
                {"role": "assistant", "content": json.dumps({"findings": findings})},
            )


class _ChatTurn:
    """One turn of the chat agent: tool calls through the loop, then the answer."""

    def __init__(
        self, builder: _Builder, distinct_id: str, trace: dict[str, Any], at: datetime, history: list[dict[str, Any]]
    ) -> None:
        self.builder = builder
        self.distinct_id = distinct_id
        self.trace = trace
        self.at = at
        self.messages = list(history)

    def step(self, tool: str, arguments: dict[str, Any], error: str | None = None) -> None:
        call = self.builder.tool_call(tool, arguments)
        assistant = {"role": "assistant", "content": "", "tool_calls": [call]}
        self.builder.generation(self.distinct_id, self.at, self.trace, list(self.messages), assistant)
        self.at += timedelta(seconds=2)
        self.builder.span(self.distinct_id, self.at, self.trace, tool, error)
        self.messages += [
            assistant,
            {"role": "tool", "tool_call_id": call["id"], "content": "error" if error else "ok"},
        ]
        self.at += timedelta(seconds=1)


def _chat(builder: _Builder, count: int) -> None:
    rng = builder.rng
    turn_index = 0
    for session in range(count):
        session_id = f"chat-{builder.uid()}"
        distinct_id = f"demo-user-{session % 40}"
        started = builder.start_time()
        history: list[dict[str, Any]] = [{"role": "system", "content": "You help people organize notes in Acme Notes."}]
        # Distinct questions per session, so the seed never reads as a user repeating a request.
        for turn_number, question in enumerate(rng.sample(list(_QUESTIONS), k=rng.choice([1, 1, 2, 2, 3, 4, 5]))):
            turn_index += 1
            history.append({"role": "user", "content": question})
            trace = {"$ai_trace_id": builder.uid(), "$ai_session_id": session_id, "ai_product": "chat_assistant"}
            turn = _ChatTurn(builder, distinct_id, trace, started + timedelta(minutes=turn_number * 3), history)
            unrecovered = turn_index % UNRECOVERED_EVERY_N_TURNS == 17
            for action_index in range(rng.randint(3, 7)):
                turn.step("run_action", {"action": rng.choice(_ACTIONS), "step": action_index, "turn": turn_index})
            # The dispatcher also refreshes the same list several times by design, which is not a loop.
            if rng.random() < 0.1:
                for _ in range(3):
                    turn.step("run_action", {"action": "list_notes", "turn": turn_index})
            if rng.random() < 0.15:
                queries = ["export pdf", "archive folder", "sync token", "version history"]
                for query in rng.sample(queries, k=rng.randint(2, 3)):
                    turn.step("search_docs", {"query": query})
            if rng.random() < 0.1:
                job = builder.uid()[:8]
                for _ in range(3):
                    turn.step("check_job_status", {"job_id": job})
            if rng.random() < 0.04:
                turn.step("search_docs", {"query": "retry"}, error="TimeoutError: search took longer than 10s")
                turn.step("search_docs", {"query": "retry"})
            if not unrecovered and rng.random() < 0.08:
                pause = "GraphInterrupt(value={'needs_approval': 'delete_notes'})"
                builder.span(distinct_id, turn.at, trace, "approval_gate", error=pause)
                history.append({"role": "assistant", "content": "This needs your approval first."})
                continue
            # Odd failing turns end on a tool call nobody retried; even ones on a failed title generation.
            tool_failure = unrecovered and turn_index % 2 == 1
            if tool_failure:
                timeout = "TimeoutError: action took longer than 30s"
                turn.step("run_action", {"action": "move_note", "step": 99, "turn": turn_index}, error=timeout)
            answer = "The action timed out, so nothing was moved yet." if tool_failure else _QUESTIONS[question]
            builder.generation(distinct_id, turn.at, trace, turn.messages, {"role": "assistant", "content": answer})
            if unrecovered and not tool_failure:
                builder.generation(
                    distinct_id,
                    turn.at + timedelta(seconds=1),
                    trace,
                    [{"role": "user", "content": "Write a short title for this conversation."}],
                    {"role": "assistant", "content": ""},
                    **{
                        "$ai_is_error": True,
                        "$ai_error": "NotFoundError: model example-title-model does not exist",
                        "$ai_span_name": "title_generation",
                    },
                )
            history.append({"role": "assistant", "content": answer})


def _scouts(builder: _Builder, count: int) -> None:
    rng = builder.rng
    for run in range(count):
        trace = {"$ai_trace_id": builder.uid(), "ai_product": "signals_scout"}
        at = builder.start_time()
        topic = rng.choice(_SCOUT_TOPICS)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You look for product signals worth a ticket."},
            {"role": "user", "content": f"Investigate {topic} in the last day."},
        ]
        for tool, arguments in (
            ("query_events", {"topic": topic, "run": run}),
            ("fetch_issue", {"topic": topic, "run": run}),
        ):
            call = builder.tool_call(tool, arguments)
            builder.generation(
                "scout", at, trace, list(messages), {"role": "assistant", "content": "", "tool_calls": [call]}
            )
            at += timedelta(seconds=3)
            builder.span("scout", at, trace, tool)
            messages += [
                {"role": "assistant", "content": "", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": call["id"], "content": "rows"},
            ]
        finding = {
            "summary": f"{topic.capitalize()} rose after the last release",
            "signal_type": rng.choice(["anomaly", "regression", "opportunity"]),
            "confidence": rng.choice(["low", "medium", "high"]),
        }
        builder.generation(
            "scout", at + timedelta(seconds=4), trace, messages, {"role": "assistant", "content": json.dumps(finding)}
        )


def build_demo_events(now: datetime, rng: random.Random, scale: float = 1.0) -> list[DemoEvent]:
    builder = _Builder(now, rng)
    _code_reviews(builder, max(1, round(REVIEWS_PER_WEEK * scale)))
    _chat(builder, max(1, round(CHAT_SESSIONS_PER_WEEK * scale)))
    _scouts(builder, max(1, round(SCOUT_RUNS_PER_WEEK * scale)))
    return builder.events


def insert_demo_events(team_id: int, events: Sequence[DemoEvent]) -> None:
    """Write to `ai_events` in full and to `events` without the heavy properties, as ingestion does."""
    from posthog.models.ai_events.test_util import bulk_create_ai_events  # noqa: PLC0415 - dev and test helper

    bulk_create_ai_events(
        [
            {
                "event": e.event,
                "event_uuid": e.uuid,
                "distinct_id": e.distinct_id,
                "team_id": team_id,
                "timestamp": e.timestamp,
                "properties": e.properties,
            }
            for e in events
        ]
    )
    zero = "1970-01-01 00:00:00"
    for start in range(0, len(events), 1000):
        chunk = events[start : start + 1000]
        params: dict[str, Any] = {}
        values = []
        for index, e in enumerate(chunk):
            values.append("(" + ", ".join(f"%({column}_{index})s" for column in _EVENT_COLUMNS) + ", 0)")
            timestamp = e.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
            row = {
                "uuid": e.uuid,
                "event": e.event,
                "properties": json.dumps({k: v for k, v in e.properties.items() if k not in HEAVY_PROPERTY_NAMES}),
                "timestamp": timestamp,
                "team_id": team_id,
                "distinct_id": e.distinct_id,
                "elements_chain": "",
                "person_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{team_id}/{e.distinct_id}")),
                "person_properties": "{}",
                "person_created_at": zero,
                **{f"group{i}_properties": "" for i in range(5)},
                **{f"group{i}_created_at": zero for i in range(5)},
                "person_mode": "full",
                "created_at": timestamp,
                "_timestamp": e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            }
            params.update({f"{column}_{index}": row[column] for column in _EVENT_COLUMNS})
        sync_execute(BULK_INSERT_EVENT_SQL() + ", ".join(values), params, flush=False)


# Positional order of BULK_INSERT_EVENT_SQL's column list, before its trailing `_offset`.
_EVENT_COLUMNS = (
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "distinct_id",
    "elements_chain",
    "person_id",
    "person_properties",
    "person_created_at",
    *(f"group{i}_properties" for i in range(5)),
    *(f"group{i}_created_at" for i in range(5)),
    "person_mode",
    "created_at",
    "_timestamp",
)


def ensure_dead_judge(team: Team) -> Evaluation:
    """An enabled judge that filters on `ai_product = signals`, a value the scouts stopped sending."""
    evaluation = Evaluation.objects.filter(team=team, name=DEAD_JUDGE_NAME, deleted=False).first()
    if evaluation is None:
        evaluation = Evaluation.objects.create(
            team=team,
            name=DEAD_JUDGE_NAME,
            description="Checks that each scout finding cites the data it read.",
            evaluation_type="llm_judge",
            evaluation_config={
                "prompt": "Return true when every claim in the finding is backed by a tool result in the trace."
            },
            output_type="boolean",
            output_config={},
            target="trace",
            enabled=True,
            conditions=[
                {
                    "id": "scout",
                    "rollout_percentage": 100,
                    "properties": [{"key": "ai_product", "value": ["signals"], "operator": "exact", "type": "event"}],
                }
            ],
        )
    # An evaluation created minutes ago has had no chance to match anything, so age it like a real one.
    Evaluation.objects.filter(pk=evaluation.pk).update(
        created_at=timezone.now() - timedelta(days=40), updated_at=timezone.now() - timedelta(days=10)
    )
    return evaluation
