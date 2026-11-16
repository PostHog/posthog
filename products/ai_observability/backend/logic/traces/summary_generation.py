import time
from typing import Literal

from django.utils import timezone

from openai import APIStatusError, APITimeoutError
from rest_framework import exceptions

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from ...facade.contracts import TraceSummaryFailureReason, TraceSummaryJob, TraceSummaryRun
from ...llm.errors import is_context_window_error_message
from ...summarization.budget import text_repr_budget
from ...summarization.constants import DEFAULT_MODEL_OPENAI
from ...summarization.llm import summarize
from ...summarization.llm.openai import SummarizationFailedError
from ...summarization.models import SummarizationMode
from ...text_repr.formatters import TraceTextRepr
from .node_contents_queries import load_trace_nodes
from .summary import FailedSummary, ReadySummary, SummaryKey, TraceSummaryRetryableError, summary_items
from .summary_store import delete_summary, job_owns_entry, requester_fingerprint, write_summary
from .summary_text import render_trace
from .trace import Trace
from .trace_queries import load_trace, load_trace_root

# A provider answers these 4xx statuses for a transient condition, so a later attempt can succeed. 499 is a
# cancellation.
_TRANSIENT_CLIENT_STATUSES = frozenset({408, 409, 429, 499})
_MODEL = str(DEFAULT_MODEL_OPENAI)


@frozen
class SummaryFailure:
    reason: TraceSummaryFailureReason
    retryable: bool


def failure_of(error: Exception) -> SummaryFailure:
    """Classify an error from the summarization call."""
    if isinstance(error, exceptions.ValidationError):
        return SummaryFailure(reason="provider_error", retryable=True)
    # The summarization call raises its own error inside the handler of the provider's, which keeps it as context.
    provider_error = error.__context__ if isinstance(error, SummarizationFailedError) else error
    # The SDK retries a timeout before it raises, so another attempt would only add more of the same waits.
    if isinstance(provider_error, APITimeoutError):
        return SummaryFailure(reason="timeout", retryable=False)
    if isinstance(provider_error, APIStatusError) and 400 <= provider_error.status_code < 500:
        if provider_error.code == "context_length_exceeded" or is_context_window_error_message(provider_error.message):
            return SummaryFailure(reason="too_large", retryable=False)
        if provider_error.status_code not in _TRANSIENT_CLIENT_STATUSES:
            return SummaryFailure(reason="provider_error", retryable=False)
    return SummaryFailure(reason="provider_error", retryable=True)


class _Run:
    def __init__(self, job: TraceSummaryJob, team: Team, requester: User) -> None:
        self.job = job
        self.team = team
        self.requester = requester
        self.key = SummaryKey.for_job(job)
        self.started = time.monotonic()

    def ready(self, entry: ReadySummary, rendered: TraceTextRepr) -> TraceSummaryRun:
        write_summary(self.key, entry)
        return self._report("ready", None, rendered)

    def failed(self, reason: TraceSummaryFailureReason, rendered: TraceTextRepr | None = None) -> TraceSummaryRun:
        write_summary(self.key, FailedSummary(reason=reason, failed_at=timezone.now()))
        return self._report("failed", reason, rendered)

    def withdrawn(self) -> TraceSummaryRun:
        # Nobody can read the entry while the organization has no approval, and a failure kept past a new approval
        # would show a stale reason, so the entry goes and the next request starts over.
        delete_summary(self.key)
        return self._report("failed", "not_approved", None)

    def access_changed(self) -> TraceSummaryRun:
        # Every viewer with the request's fingerprint shares the entry, so a failure kept here would tell viewers whose
        # access did not change that theirs did.
        delete_summary(self.key)
        return self._report("failed", "access_changed", None)

    def _report(
        self,
        status: Literal["ready", "failed"],
        reason: TraceSummaryFailureReason | None,
        rendered: TraceTextRepr | None,
    ) -> TraceSummaryRun:
        return TraceSummaryRun(
            status=status,
            failure_reason=reason,
            duration_ms=round((time.monotonic() - self.started) * 1000),
            input_characters=len(rendered.text) if rendered else 0,
            model=_MODEL,
            was_sampled=rendered.was_sampled if rendered else False,
            distinct_id=self.requester.distinct_id or str(self.team.uuid),
            groups=groups(self.team.organization, self.team),
        )


def generate_summary(job: TraceSummaryJob, *, final_attempt: bool) -> TraceSummaryRun | None:
    """Write the job's summary entry as `ready` or `failed` and report what the run did, or return None when the
    entry no longer waits for this job.

    Raises `TraceSummaryRetryableError`, leaving the entry `pending`, when a later attempt can still succeed.
    An unexpected error is raised for Temporal to retry, and on the final attempt it writes `failed` instead."""
    if not job_owns_entry(job):
        return None
    team = Team.objects.select_related("organization").get(pk=job.team_id)
    run = _Run(job, team, User.objects.get(pk=job.requester_id))
    try:
        return _generate(run, final_attempt=final_attempt)
    except TraceSummaryRetryableError:
        raise
    except Exception as error:
        if not final_attempt:
            raise
        capture_exception(error, additional_properties={"team_id": job.team_id})
        return run.failed("error")


def _generate(run: _Run, *, final_attempt: bool) -> TraceSummaryRun:
    job, team, requester = run.job, run.team, run.requester
    if not team.organization.is_ai_data_processing_approved:
        return run.withdrawn()
    # The entry is keyed by the fingerprint the request saw, so content the requester can no longer read must not
    # reach it.
    if requester_fingerprint(team.pk, requester) != job.fingerprint:
        return run.access_changed()
    loaded = load_trace(team, requester, job.trace_id, job.timestamp_hint)
    if not loaded.rows:
        return run.failed("trace_not_found")
    trace = Trace(job.trace_id, loaded.rows, loaded.person)
    root = load_trace_root(team, requester, job.trace_id, trace.created_at)
    step_ids = [event.id for event in trace.events if not event.is_trace_event]
    steps = load_trace_nodes(team, requester, job.trace_id, step_ids, trace.created_at)
    # Each read applies the restrictions in force when it runs. A change during the reads could put content under
    # an entry whose viewers may not read it.
    if requester_fingerprint(team.pk, requester) != job.fingerprint:
        return run.access_changed()
    rendered = render_trace(trace, root.trace_event, steps, text_repr_budget())
    try:
        response = summarize(
            rendered.text,
            team.pk,
            mode=SummarizationMode.MINIMAL,
            user_id=requester.distinct_id,
            flex=False,
            final_attempt=final_attempt,
        )
    except (SummarizationFailedError, exceptions.ValidationError) as error:
        failure = failure_of(error)
        if failure.retryable and not final_attempt:
            raise TraceSummaryRetryableError(failure.reason) from error
        return run.failed(failure.reason, rendered)
    return run.ready(
        ReadySummary(
            title=response.title,
            bullets=summary_items([(b.text, b.line_refs) for b in response.summary_bullets], rendered.line_owners),
            notes=summary_items([(n.text, n.line_refs) for n in response.interesting_notes], rendered.line_owners),
            flow=response.flow_diagram,
            model=_MODEL,
            generated_at=timezone.now(),
        ),
        rendered,
    )
