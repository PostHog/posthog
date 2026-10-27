import re
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

import httpx
import openai
from parameterized import parameterized

from posthog.models import User
from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.facade.contracts import TraceSummaryFailureReason, TraceSummaryJob
from products.ai_observability.backend.logic.traces.summary import (
    FailedSummary,
    PendingSummary,
    ReadySummary,
    SummaryItem,
    SummaryKey,
    TraceSummaryRetryableError,
)
from products.ai_observability.backend.logic.traces.summary_generation import generate_summary
from products.ai_observability.backend.logic.traces.summary_store import (
    read_summary,
    requester_fingerprint,
    write_summary,
)
from products.ai_observability.backend.summarization.llm import summarize as real_summarize
from products.ai_observability.backend.summarization.llm.schema import (
    InterestingNote,
    SummarizationResponse,
    SummaryBullet,
)

from ...property_access import hide_event_property
from .rows import T0

SPAN = "00000000-0000-0000-0000-000000000001"
GENERATION = "00000000-0000-0000-0000-000000000002"
QUESTION = "How do I export my invoices as CSV?"
PRIVATE_NOTE = "account manager notes: renewal at risk"
REQUEST = httpx.Request("POST", "https://gateway.example.com/v1/chat/completions")


def _status_error(status: int, code: str | None = None, message: str = "provider error") -> openai.APIStatusError:
    return openai.APIStatusError(
        message, response=httpx.Response(status, request=REQUEST), body={"code": code} if code else None
    )


def _response(bullet_ref: str) -> SummarizationResponse:
    return SummarizationResponse(
        title="Invoice export question",
        flow_diagram="question → answer",
        summary_bullets=[
            SummaryBullet(text="The user asks about CSV exports.", line_refs=bullet_ref),
            SummaryBullet(text="The answer points to settings.", line_refs=""),
        ],
        interesting_notes=[InterestingNote(text="No follow-up.", line_refs="")],
    )


class TestGenerateSummary(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("products.ai_observability.backend.logic.traces.summary_generation.summarize")
        self.summarize = patcher.start()
        self.addCleanup(patcher.stop)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_span",
                    "event_uuid": SPAN,
                    "distinct_id": "user-1",
                    "team": self.team,
                    "timestamp": T0,
                    "properties": {"$ai_trace_id": "trace-1", "$ai_span_id": "span-1", "$ai_span_name": "answer"},
                },
                {
                    "event": "$ai_generation",
                    "event_uuid": GENERATION,
                    "distinct_id": "user-1",
                    "team": self.team,
                    "timestamp": T0,
                    "properties": {
                        "$ai_trace_id": "trace-1",
                        "$ai_parent_id": "span-1",
                        "$ai_model": "gpt-4.1-mini",
                        "$ai_input": [
                            {"role": "user", "content": QUESTION},
                            {"role": "system", "content": PRIVATE_NOTE},
                        ],
                    },
                },
            ]
        )

    def _job(self, user: User | None = None, *, trace_id: str = "trace-1") -> TraceSummaryJob:
        requester = user or self.user
        job = TraceSummaryJob(
            team_id=self.team.pk,
            trace_id=trace_id,
            timestamp_hint=T0,
            fingerprint=requester_fingerprint(self.team.pk, requester),
            requester_id=requester.pk,
            requested_at=T0,
        )
        write_summary(SummaryKey.for_job(job), PendingSummary(requested_at=T0))
        return job

    def _provider_fails_with(self, error: Exception) -> None:
        # The real summarization call runs against a client that fails, so the test sees the error as that call
        # wraps it.
        client = MagicMock()
        client.chat.completions.create.side_effect = error
        self.enterContext(
            patch("products.ai_observability.backend.summarization.llm.openai.build_openai_client", return_value=client)
        )
        self.summarize.side_effect = real_summarize

    def test_writes_a_ready_summary_with_step_links(self) -> None:
        def answer(text_repr: str, *args: Any, **kwargs: Any) -> SummarizationResponse:
            question_line = next(line for line in text_repr.split("\n") if QUESTION in line)
            ref = re.match(r"L\d+", question_line)
            assert ref is not None
            return _response(ref.group(0))

        self.summarize.side_effect = answer
        job = self._job()

        run = generate_summary(job, final_attempt=True)

        entry = read_summary(SummaryKey.for_job(job))
        assert isinstance(entry, ReadySummary)
        assert [item.node_id for item in entry.bullets] == [GENERATION, None]
        assert entry.notes == (SummaryItem(text="No follow-up.", node_id=None),)
        assert (run.status, run.input_characters) == ("ready", len(self.summarize.call_args.args[0]))

    def test_restricted_content_never_reaches_the_model(self) -> None:
        self.summarize.return_value = _response("")
        hide_event_property(self.team, self.user, "$ai_input")

        generate_summary(self._job(), final_attempt=True)

        text_repr = self.summarize.call_args.args[0]
        assert "answer" in text_repr and PRIVATE_NOTE not in text_repr

    @parameterized.expand([("access_changed",), ("trace_not_found",)])
    def test_refuses_without_calling_the_model(self, reason: TraceSummaryFailureReason) -> None:
        job = self._job(trace_id="trace-2" if reason == "trace_not_found" else "trace-1")
        if reason == "access_changed":
            hide_event_property(self.team, self.user, "$ai_input")

        run = generate_summary(job, final_attempt=True)

        self.summarize.assert_not_called()
        entry = read_summary(SummaryKey.for_job(job))
        assert isinstance(entry, FailedSummary) and (entry.reason, run.failure_reason) == (reason, reason)

    def test_withdrawn_approval_drops_the_entry_without_calling_the_model(self) -> None:
        job = self._job()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        run = generate_summary(job, final_attempt=True)

        self.summarize.assert_not_called()
        assert read_summary(SummaryKey.for_job(job)) is None
        assert (run.status, run.failure_reason) == ("failed", "not_approved")

    @parameterized.expand(
        [
            ("a bad request fails at once", _status_error(400), False, "provider_error"),
            ("too long for the model", _status_error(400, "context_length_exceeded"), False, "too_large"),
            (
                "too long, said only in the message",
                _status_error(400, message="This model's maximum context length is 128000 tokens."),
                False,
                "too_large",
            ),
            ("an outage on the last attempt", _status_error(503), True, "provider_error"),
            ("a timeout on the last attempt", openai.APITimeoutError(request=REQUEST), True, "timeout"),
        ]
    )
    def test_provider_failures(
        self,
        _name: str,
        error: Exception,
        final_attempt: bool,
        expected: TraceSummaryFailureReason,
    ) -> None:
        self._provider_fails_with(error)
        job = self._job()

        run = generate_summary(job, final_attempt=final_attempt)

        entry = read_summary(SummaryKey.for_job(job))
        assert isinstance(entry, FailedSummary) and (entry.reason, run.status) == (expected, "failed")

    @parameterized.expand([("an outage", 503), ("a rate limit", 429), ("a cancelled request", 499)])
    def test_a_transient_failure_with_a_retry_left_keeps_the_entry_pending(self, _name: str, status: int) -> None:
        self._provider_fails_with(_status_error(status))
        job = self._job()

        with pytest.raises(TraceSummaryRetryableError):
            generate_summary(job, final_attempt=False)
        assert isinstance(read_summary(SummaryKey.for_job(job)), PendingSummary)
