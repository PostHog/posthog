import re
import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal, Self

from posthog.dataclasses import frozen
from posthog.temporal.common.errors import NonReportableError

from ...facade.contracts import TraceSummaryFailureReason, TraceSummaryJob
from ...summarization.constants import SUMMARIZATION_TIMEOUT

# The OpenAI client retries a failed call twice by default, each attempt with the full timeout.
LLM_CALL_DEADLINE = timedelta(seconds=SUMMARIZATION_TIMEOUT * 3)
ATTEMPT_DEADLINE = LLM_CALL_DEADLINE + timedelta(minutes=2)
MAX_ATTEMPTS = 2
RETRY_INITIAL_INTERVAL = timedelta(seconds=15)
RETRY_BACKOFF = 2.0
RETRY_MAX_INTERVAL = timedelta(seconds=60)
HEARTBEAT_TIMEOUT = timedelta(seconds=60)
JOB_DEADLINE = MAX_ATTEMPTS * ATTEMPT_DEADLINE + RETRY_MAX_INTERVAL
# Marking an abandoned entry failed is one cache write, retried a few times.
FAIL_DEADLINE = timedelta(minutes=2)
WORKFLOW_DEADLINE = JOB_DEADLINE + FAIL_DEADLINE
# A pending entry outlives the workflow, so a job lost before it writes its result expires and can be requested again.
PENDING_TTL = WORKFLOW_DEADLINE + timedelta(minutes=1)
READY_TTL = timedelta(hours=1)
FAILED_TTL = timedelta(minutes=5)

FAILURE_MESSAGES: dict[TraceSummaryFailureReason, str] = {
    "trace_not_found": "We couldn't find this trace's events. They may have expired.",
    "too_large": "This trace is too large to summarize.",
    "timeout": "The model took too long to answer. Try again.",
    "provider_error": "The model provider returned an error. Try again in a few minutes.",
    "not_approved": "Your organization hasn't approved AI data processing.",
    "access_changed": "Your data access changed while the summary was being written. Try again.",
    "error": "Something went wrong while summarizing. Try again.",
}

_LINE_REF = re.compile(r"L(\d+)")


class AIDataProcessingNotApprovedError(Exception):
    pass


class TraceSummaryNotFoundError(Exception):
    pass


# Not reported: a later attempt runs, and the final attempt reports the failure that costs the user their summary.
class TraceSummaryRetryableError(NonReportableError):
    def __init__(self, reason: TraceSummaryFailureReason) -> None:
        super().__init__(reason)
        self.reason = reason


def require_ai_data_processing_approval(approved: bool | None) -> None:
    if not approved:
        raise AIDataProcessingNotApprovedError()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@frozen
class SummaryKey:
    team_id: int
    trace_id: str
    fingerprint: str

    @classmethod
    def for_job(cls, job: TraceSummaryJob) -> Self:
        return cls(team_id=job.team_id, trace_id=job.trace_id, fingerprint=job.fingerprint)

    @property
    def cache_key(self) -> str:
        # Hashing bounds the key for any trace id, and the version lets the entry shape change without reading old values.
        return f"ai_observability:trace_summary:v1:{self.team_id}:{_sha256(self.trace_id)}:{self.fingerprint}"


def workflow_id(job: TraceSummaryJob) -> str:
    """One workflow per pending entry: requests that share an entry share its run, and a new entry gets a new run
    even while the previous run is closing."""
    pending = f"{SummaryKey.for_job(job).cache_key}:{job.requested_at.isoformat()}"
    return f"ai-observability-trace-summary-{_sha256(pending)}"


@frozen
class SummaryItem:
    text: str
    node_id: str | None


@frozen
class PendingSummary:
    requested_at: datetime
    status: Literal["pending"] = "pending"


@frozen
class ReadySummary:
    title: str
    bullets: tuple[SummaryItem, ...]
    notes: tuple[SummaryItem, ...]
    flow: str
    model: str
    generated_at: datetime
    status: Literal["ready"] = "ready"


@frozen
class FailedSummary:
    reason: TraceSummaryFailureReason
    failed_at: datetime
    status: Literal["failed"] = "failed"

    @property
    def message(self) -> str:
        return FAILURE_MESSAGES[self.reason]


SummaryEntry = PendingSummary | ReadySummary | FailedSummary
RequestPlan = Literal["return", "claim", "replace", "attach"]


def plan_request(existing: SummaryEntry | None, regenerate: bool) -> RequestPlan:
    match existing:
        case None:
            return "claim"
        case PendingSummary():
            return "attach"
        case ReadySummary():
            return "replace" if regenerate else "return"
        case FailedSummary():
            return "replace"


def ttl_for(entry: SummaryEntry) -> timedelta:
    match entry:
        case PendingSummary():
            return PENDING_TTL
        case ReadySummary():
            return READY_TTL
        case FailedSummary():
            return FAILED_TTL


def line_number(ref: str) -> int | None:
    match = _LINE_REF.fullmatch(ref)
    return int(match.group(1)) if match else None


def summary_items(items: Sequence[tuple[str, str]], line_owners: Sequence[str | None]) -> tuple[SummaryItem, ...]:
    """Each `(text, line reference)` pair as an item linked to the step that owns the referenced line."""

    def owner(ref: str) -> str | None:
        number = line_number(ref)
        return line_owners[number - 1] if number is not None and 0 < number <= len(line_owners) else None

    return tuple(SummaryItem(text=text, node_id=owner(ref)) for text, ref in items)
