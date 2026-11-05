import uuid
from datetime import UTC, datetime, timedelta

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.facade.contracts import TraceSummaryJob
from products.ai_observability.backend.logic.traces.summary import (
    FailedSummary,
    PendingSummary,
    ReadySummary,
    SummaryEntry,
    SummaryItem,
    SummaryKey,
)
from products.ai_observability.backend.logic.traces.summary_store import (
    claim_summary,
    fail_abandoned_summary,
    read_summary,
    write_summary,
)

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
READY = ReadySummary(
    title="Refund request",
    bullets=(SummaryItem(text="The user asks for a refund.", node_id="gen-1"),),
    notes=(SummaryItem(text="No order number given.", node_id=None),),
    flow="ask → refuse",
    model="gpt-4.1-mini",
    generated_at=T0,
)


class TestSummaryStore(SimpleTestCase):
    def setUp(self) -> None:
        self.key = SummaryKey(team_id=1, trace_id=str(uuid.uuid4()), fingerprint="f")

    def tearDown(self) -> None:
        cache.delete(self.key.cache_key)

    @parameterized.expand(
        [
            ("pending", PendingSummary(requested_at=T0)),
            ("ready", READY),
            ("failed", FailedSummary(reason="too_large", failed_at=T0)),
        ]
    )
    def test_round_trips_each_entry(self, _name: str, entry: SummaryEntry) -> None:
        write_summary(self.key, entry)

        assert read_summary(self.key) == entry

    @parameterized.expand([("not json", "not json"), ("an unknown status", '{"status": "archived"}'), ("a dict", {})])
    def test_an_unreadable_value_reads_as_no_summary(self, _name: str, value: object) -> None:
        cache.set(self.key.cache_key, value)

        assert read_summary(self.key) is None

    def test_claim_never_overwrites(self) -> None:
        first = PendingSummary(requested_at=T0)

        assert claim_summary(self.key, first)
        assert not claim_summary(self.key, PendingSummary(requested_at=datetime(2026, 9, 2, tzinfo=UTC)))
        assert read_summary(self.key) == first

    @parameterized.expand(
        [
            ("the job's pending entry fails", PendingSummary(requested_at=T0), "failed"),
            ("a newer request's entry stays", PendingSummary(requested_at=T0 + timedelta(seconds=5)), "pending"),
            ("a written result stays", READY, "ready"),
        ]
    )
    def test_an_abandoned_job_fails_only_its_own_pending_entry(
        self, _name: str, entry: SummaryEntry, expected_status: str
    ) -> None:
        write_summary(self.key, entry)
        job = TraceSummaryJob(
            team_id=self.key.team_id,
            trace_id=self.key.trace_id,
            timestamp_hint=None,
            fingerprint=self.key.fingerprint,
            requester_id=7,
            requested_at=T0,
        )

        fail_abandoned_summary(job)

        stored = read_summary(self.key)
        assert stored is not None and stored.status == expected_status
