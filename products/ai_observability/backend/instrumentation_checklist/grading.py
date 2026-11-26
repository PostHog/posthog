from collections.abc import Iterable, Sequence
from enum import StrEnum

from posthog.dataclasses import frozen

# A check gets its own page where one covers the instrumentation it asks for, and the installation
# page otherwise. Sending a reader to a page that does not answer the question the check just raised
# is worse than leaving them on installation.
from products.ai_observability.backend.logic.docs_urls import INSTALLATION_DOCS_URL, SESSIONS_DOCS_URL, TOOLS_DOCS_URL
from products.ai_observability.backend.logic.instrumentation.signals import (
    FIRST_EVENT_FLOOR,
    SignalGrade,
    answers_session,
    grade_signal,
)

# Tool calls are the one check that needs volume: a project that does use tools can still go many
# generations without calling one. The other checks read a property the SDK sets on every event or
# never sets, so one event answers them and a first test gets its verdict at once.
VOLUME_FLOOR = 20

_PENDING_FIRST_GENERATION = "Waiting for your first generation. This check runs as soon as one arrives."
_PENDING_FIRST_AI_EVENT = "Waiting for your first AI event. This check runs as soon as one arrives."
_PENDING_TOOL_CALLS = f"Still collecting data. This check runs once there are {VOLUME_FLOOR} generations."


class CheckKey(StrEnum):
    SESSIONS = "sessions"
    TOOL_CALLS = "tool_calls"
    USER_IDENTITY = "user_identity"
    TRACE_STRUCTURE = "trace_structure"


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    PENDING = "pending"
    DISMISSED = "dismissed"


@frozen
class ChecklistStats:
    generations: int
    events_with_session: int
    events_declining_session: int
    generations_with_tool_calls: int
    sdk_generations: int
    sdk_generations_identified: int
    spans: int
    events_with_parent: int
    total_events: int
    # Whether any generation carried tool definitions. `None` when nothing asked: a project that
    # already records tool calls never needs the answer, and the read behind it is expensive.
    tools_declared: bool | None = None

    def __post_init__(self) -> None:
        counted = self.generations + self.spans
        if self.total_events < counted:
            raise ValueError(
                f"total_events ({self.total_events}) is below the {counted} generations and spans already counted, "
                "so the trace structure check would be graded against a denominator that cannot be real"
            )


@frozen
class GradedCheck:
    key: CheckKey
    status: CheckStatus
    title: str
    detail: str
    docs_url: str
    stats: dict[str, int]


@frozen
class ChecklistProgress:
    passing: int
    total: int


# A dismissed check counts as passing: the person decided it does not apply, so it no longer asks for work.
PASSING_STATUSES = frozenset({CheckStatus.OK, CheckStatus.DISMISSED})


@frozen
class _CheckInputs:
    key: CheckKey
    title: str
    denominator: int
    floor: int
    has_signal: bool
    warning_detail: str
    ok_detail: str
    pending_detail: str
    docs_url: str
    stats: dict[str, int]


def _sessions(stats: ChecklistStats) -> _CheckInputs:
    # A missing session id cannot tell incomplete instrumentation apart from a workload that
    # genuinely finishes in one trace, so a project that sent an explicit null has answered the
    # question and the copy has to reflect which of the two earned the ok.
    if stats.events_with_session > 0:
        ok_detail = "Traces are grouping into sessions."
    else:
        ok_detail = "Traces are marked as finishing in one trace, so there is nothing to group."

    return _CheckInputs(
        key=CheckKey.SESSIONS,
        title="Sessions",
        denominator=stats.generations,
        floor=FIRST_EVENT_FLOOR,
        has_signal=answers_session(
            with_session=stats.events_with_session, declining_session=stats.events_declining_session
        ),
        warning_detail=(
            "No traces include $ai_session_id. If your product has multi-turn conversations, setting it lets us "
            "group them into sessions. Workloads that are complete in one trace, like batch jobs or one-shot "
            "generation, do not need it. Send $ai_session_id as null on those to say so."
        ),
        ok_detail=ok_detail,
        pending_detail=_PENDING_FIRST_GENERATION,
        docs_url=SESSIONS_DOCS_URL,
        stats={
            "generations": stats.generations,
            "events_with_session": stats.events_with_session,
            "events_declining_session": stats.events_declining_session,
        },
    )


def _tool_calls(stats: ChecklistStats) -> _CheckInputs:
    # Tool definitions arriving without any call points at an SDK or parser problem, while no definitions
    # at all usually just means the app does not use tools, so the two warnings ask for different things.
    if stats.tools_declared:
        warning_detail = (
            "No tool calls recorded, but you are sending tool definitions. If your agent does call tools, check "
            "that your SDK version reports them."
        )
    else:
        warning_detail = (
            "No tool calls recorded. If your app uses tool or function calling, capture it to see which tools run "
            "and how often."
        )

    return _CheckInputs(
        key=CheckKey.TOOL_CALLS,
        title="Tool calls",
        denominator=stats.generations,
        floor=VOLUME_FLOOR,
        has_signal=stats.generations_with_tool_calls > 0,
        warning_detail=warning_detail,
        ok_detail="Tool calls are being recorded.",
        pending_detail=_PENDING_TOOL_CALLS,
        docs_url=TOOLS_DOCS_URL,
        stats={
            "generations": stats.generations,
            "generations_with_tool_calls": stats.generations_with_tool_calls,
        },
    )


def _user_identity(stats: ChecklistStats) -> _CheckInputs:
    return _CheckInputs(
        key=CheckKey.USER_IDENTITY,
        title="User identity",
        denominator=stats.sdk_generations,
        floor=FIRST_EVENT_FLOOR,
        has_signal=stats.sdk_generations_identified > 0,
        warning_detail=(
            "Generations are arriving with their trace ID as the distinct ID, so usage and cost cannot be tied to "
            "people. Set distinct_id to your own user identifier."
        ),
        ok_detail="AI events are attributed to identified users.",
        pending_detail=(
            "Waiting for your first generation from a PostHog SDK. Generations sent over OpenTelemetry are not "
            "counted, because we cannot tell whether they are identified."
        ),
        docs_url=INSTALLATION_DOCS_URL,
        stats={
            "sdk_generations": stats.sdk_generations,
            "sdk_generations_identified": stats.sdk_generations_identified,
        },
    )


def _trace_structure(stats: ChecklistStats) -> _CheckInputs:
    return _CheckInputs(
        key=CheckKey.TRACE_STRUCTURE,
        title="Trace structure",
        # Flooring on generations would leave a project that only emits spans and traces pending forever.
        denominator=stats.total_events,
        floor=FIRST_EVENT_FLOOR,
        has_signal=stats.spans > 0 or stats.events_with_parent > 0,
        warning_detail=(
            "Without spans, a trace shows LLM calls but not the retrieval, chains or sub-agent steps around them."
        ),
        # A generation carrying $ai_parent_id is enough structure to grade ok even with no $ai_span
        # event, so the copy cannot name spans.
        ok_detail="Traces show the steps around your LLM calls.",
        pending_detail=_PENDING_FIRST_AI_EVENT,
        docs_url=INSTALLATION_DOCS_URL,
        stats={
            "total_events": stats.total_events,
            "spans": stats.spans,
            "events_with_parent": stats.events_with_parent,
        },
    )


def _grade(inputs: _CheckInputs, *, dismissed: bool) -> GradedCheck:
    match grade_signal(events=inputs.denominator, floor=inputs.floor, has_signal=inputs.has_signal):
        case SignalGrade.PENDING:
            graded_status, detail = CheckStatus.PENDING, inputs.pending_detail
        case SignalGrade.MISSING:
            graded_status, detail = CheckStatus.WARNING, inputs.warning_detail
        case SignalGrade.PRESENT:
            graded_status, detail = CheckStatus.OK, inputs.ok_detail

    # Dismissal only overrides the status. The detail stays the one the counts earned, so a muted row
    # still says what the user silenced and what "Recheck" would re-evaluate.
    return GradedCheck(
        key=inputs.key,
        status=CheckStatus.DISMISSED if dismissed else graded_status,
        title=inputs.title,
        detail=detail,
        docs_url=inputs.docs_url,
        stats=inputs.stats,
    )


def grade_checklist(stats: ChecklistStats, dismissed_keys: Iterable[str]) -> list[GradedCheck]:
    dismissed = set(dismissed_keys)
    checks = [build(stats) for build in (_sessions, _tool_calls, _user_identity, _trace_structure)]
    return [_grade(check, dismissed=check.key in dismissed) for check in checks]


def checklist_progress(checks: Sequence[GradedCheck]) -> ChecklistProgress:
    return ChecklistProgress(passing=sum(1 for check in checks if check.status in PASSING_STATUSES), total=len(checks))


def agent_prompt(checks: Sequence[GradedCheck]) -> str | None:
    warnings = [check for check in checks if check.status == CheckStatus.WARNING]
    if not warnings:
        return None
    items = "\n".join(f"- {check.title}: {check.detail} Docs: {check.docs_url}" for check in warnings)
    return (
        "My PostHog AI observability setup is missing some instrumentation. Fix each item below in this "
        f"codebase, following the linked docs.\n\n{items}"
    )
