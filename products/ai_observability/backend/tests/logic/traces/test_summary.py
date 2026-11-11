from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.ai_observability.backend.facade.contracts import TraceSummaryJob
from products.ai_observability.backend.logic.traces.summary import (
    ATTEMPT_DEADLINE,
    JOB_DEADLINE,
    LLM_CALL_DEADLINE,
    MAX_ATTEMPTS,
    WORKFLOW_DEADLINE,
    FailedSummary,
    PendingSummary,
    ReadySummary,
    RequestPlan,
    SummaryEntry,
    SummaryItem,
    SummaryKey,
    plan_request,
    summary_items,
    ttl_for,
    workflow_id,
)

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
PENDING = PendingSummary(requested_at=T0)
READY = ReadySummary(title="Refund request", bullets=(), notes=(), flow="ask → answer", model="m", generated_at=T0)
FAILED = FailedSummary(reason="provider_error", failed_at=T0)


@parameterized.expand(
    [
        ("nothing stored", None, False, "claim"),
        ("ready, no regenerate", READY, False, "return"),
        ("ready, regenerate", READY, True, "replace"),
        ("failed, retried without regenerate", FAILED, False, "replace"),
        ("pending, regenerate", PENDING, True, "attach"),
    ]
)
def test_plan_request(_name: str, existing: SummaryEntry | None, regenerate: bool, expected: RequestPlan) -> None:
    assert plan_request(existing, regenerate) == expected


def _job(
    team_id: int = 1, trace_id: str = "trace-1", fingerprint: str = "a", requested_at: datetime = T0
) -> TraceSummaryJob:
    return TraceSummaryJob(
        team_id=team_id,
        trace_id=trace_id,
        timestamp_hint=None,
        fingerprint=fingerprint,
        requester_id=7,
        requested_at=requested_at,
    )


def test_keys_and_runs_differ_by_team_trace_fingerprint_and_request_and_stay_bounded() -> None:
    jobs = [
        _job(),
        _job(team_id=2),
        _job(trace_id="trace-2"),
        _job(fingerprint="b"),
        _job(requested_at=T0 + timedelta(seconds=1)),
    ]
    long_job = _job(trace_id="t" * 5000, fingerprint="a" * 64)

    assert len({SummaryKey.for_job(job).cache_key for job in jobs}) == 4
    assert len({workflow_id(job) for job in jobs}) == 5
    assert workflow_id(_job()) == workflow_id(_job())
    assert len(SummaryKey.for_job(long_job).cache_key) < 200 and len(workflow_id(long_job)) < 200


@parameterized.expand(
    [
        ("zero padded", "L045", "gen-b"),
        ("unpadded", "L3", "gen-a"),
        ("a header line", "L1", None),
        ("past the end", "L999", None),
        ("line zero", "L0", None),
        ("no reference", "", None),
    ]
)
def test_summary_items_link_each_line_to_its_step(_name: str, ref: str, node_id: str | None) -> None:
    owners = [None, None, "gen-a", *["gen-b"] * 50]

    assert summary_items([("text", ref)], owners) == (SummaryItem(text="text", node_id=node_id),)


def test_a_lost_job_expires_before_it_can_be_requested_again() -> None:
    assert ATTEMPT_DEADLINE > LLM_CALL_DEADLINE
    assert JOB_DEADLINE >= MAX_ATTEMPTS * ATTEMPT_DEADLINE
    assert WORKFLOW_DEADLINE > JOB_DEADLINE
    assert ttl_for(PENDING) > WORKFLOW_DEADLINE
