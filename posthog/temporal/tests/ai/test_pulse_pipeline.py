import pytest

from asgiref.sync import sync_to_async

from posthog.models.pulse import PulseDigest, PulseDigestStatus, PulseFinding
from posthog.models.scoping import team_scope
from posthog.temporal.ai.pulse.delivery import persist_findings
from posthog.temporal.ai.pulse.types import EnrichedFinding, MetricDescriptor
from posthog.temporal.ai.pulse.workflow import create_or_get_digest_activity, set_workflow_run_id_activity

PERIOD = "2026-W22"
START = "2026-05-22T00:00:00+00:00"
END = "2026-05-29T00:00:00+00:00"


def _enriched(label: str = "$pageview", evidence: dict | None = None) -> EnrichedFinding:
    return EnrichedFinding(
        descriptor=MetricDescriptor(source="top_event", source_id=1, label=label, query={"kind": "TrendsQuery"}),
        current_value=50.0,
        baseline_value=100.0,
        change_pct=-0.5,
        impact=5.0,
        robust_z=4.2,
        attribution_breakdown={"$browser": "Safari"},
        evidence=evidence,
        narrative="Pageviews dropped by half.",
    )


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_create_or_get_digest_creates_one_per_period(ateam):
    first = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)
    second = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)

    assert first == second  # same digest reused for the same period

    @sync_to_async
    def _count() -> int:
        with team_scope(ateam.id, canonical=True):
            return PulseDigest.objects.filter(team_id=ateam.id).count()

    assert await _count() == 1


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_create_or_get_digest_distinct_periods(ateam):
    a = await create_or_get_digest_activity(ateam.id, "2026-W22", START, END)
    b = await create_or_get_digest_activity(
        ateam.id, "2026-W23", "2026-05-29T00:00:00+00:00", "2026-06-05T00:00:00+00:00"
    )
    assert a != b


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_digest_access_requires_team_scope(ateam):
    from posthog.models.scoping.manager import TeamScopeError

    await create_or_get_digest_activity(ateam.id, PERIOD, START, END)

    @sync_to_async
    def _unscoped_read() -> None:
        # No team_scope -> fail-closed manager must raise.
        list(PulseDigest.objects.filter(team_id=ateam.id))

    with pytest.raises(TeamScopeError):
        await _unscoped_read()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_persist_findings_is_idempotent_on_retry(ateam):
    digest_id = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)
    findings = [_enriched("$pageview"), _enriched("$autocapture")]

    ids_first = await persist_findings(ateam.id, digest_id, findings)
    ids_second = await persist_findings(ateam.id, digest_id, findings)  # simulates a Temporal retry

    assert ids_first == ids_second  # same finding ids returned, no new rows

    @sync_to_async
    def _findings():
        with team_scope(ateam.id, canonical=True):
            rows = list(PulseFinding.objects.filter(digest_id=digest_id))
            return rows, [r.team_id for r in rows], PulseDigest.objects.get(id=digest_id).status

    rows, team_ids, status = await _findings()
    assert len(rows) == 2  # no duplicates
    assert all(tid == ateam.id for tid in team_ids)  # team_id denormalized from digest
    assert status == PulseDigestStatus.DELIVERED


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_persist_findings_persists_evidence(ateam):
    digest_id = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)
    finding = _enriched("$pageview", evidence={"session_ids": ["abc", "def"]})

    await persist_findings(ateam.id, digest_id, [finding])

    @sync_to_async
    def _evidence():
        with team_scope(ateam.id, canonical=True):
            return PulseFinding.objects.get(digest_id=digest_id).evidence

    assert await _evidence() == {"session_ids": ["abc", "def"]}


def test_root_cause_message_walks_temporal_cause_chain():
    from posthog.temporal.ai.pulse.workflow import _root_cause_message

    class _Err(Exception):
        def __init__(self, message, cause=None):
            super().__init__(message)
            self.message = message
            self.cause = cause

    # ActivityError("Activity task failed") -> ApplicationError(real message)
    leaf = _Err("ImportError: cannot import name 'Dashboard'")
    wrapper = _Err("Activity task failed", cause=leaf)
    assert _root_cause_message(wrapper) == "ImportError: cannot import name 'Dashboard'"
    # Plain exception with no .cause/.message falls back to str().
    assert _root_cause_message(ValueError("boom")) == "boom"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_persist_findings_short_circuits_when_already_delivered(ateam):
    digest_id = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)
    await persist_findings(ateam.id, digest_id, [_enriched("$pageview")])

    # A second invocation with different findings must NOT overwrite a DELIVERED digest.
    ids = await persist_findings(ateam.id, digest_id, [_enriched("different")])

    @sync_to_async
    def _labels():
        with team_scope(ateam.id, canonical=True):
            return list(PulseFinding.objects.filter(digest_id=digest_id).values_list("metric_label", flat=True))

    labels = await _labels()
    assert labels == ["$pageview"]  # original findings preserved
    assert len(ids) == 1


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_set_workflow_run_id_activity(ateam):
    digest_id = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)
    await set_workflow_run_id_activity(ateam.id, digest_id, "run-abc-123")

    @sync_to_async
    def _run_id() -> str:
        with team_scope(ateam.id, canonical=True):
            return PulseDigest.objects.get(id=digest_id).workflow_run_id

    assert await _run_id() == "run-abc-123"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_full_scan_rerun_is_idempotent(ateam):
    """Two scans for the same period reuse one digest and never duplicate findings."""
    findings = [_enriched("$pageview"), _enriched("$autocapture")]

    # First scan
    digest_a = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)
    await set_workflow_run_id_activity(ateam.id, digest_a, "run-1")
    await persist_findings(ateam.id, digest_a, findings)

    # Second scan for the same period (e.g. dispatcher re-run / Temporal replay)
    digest_b = await create_or_get_digest_activity(ateam.id, PERIOD, START, END)
    await set_workflow_run_id_activity(ateam.id, digest_b, "run-2")
    await persist_findings(ateam.id, digest_b, findings)

    assert digest_a == digest_b

    @sync_to_async
    def _counts():
        with team_scope(ateam.id, canonical=True):
            return (
                PulseDigest.objects.filter(team_id=ateam.id).count(),
                PulseFinding.objects.filter(digest_id=digest_a).count(),
                PulseDigest.objects.get(id=digest_a).workflow_run_id,
            )

    digest_count, finding_count, run_id = await _counts()
    assert digest_count == 1
    assert finding_count == 2
    assert run_id == "run-2"  # run_id is overwritten each scan; findings are not
