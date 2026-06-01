"""PulseScanWorkflow — orchestrates proactive insight scans for one team."""

import json
from datetime import datetime, timedelta

import structlog
from pydantic import BaseModel
from temporalio import activity, common, workflow

from posthog.models import PulseDigest
from posthog.models.pulse import PulseDigestStatus, PulseSubscription
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse import metrics
from posthog.temporal.ai.pulse.delivery import notify_digest, persist_findings
from posthog.temporal.ai.pulse.detection import detect_changes
from posthog.temporal.ai.pulse.narrative import enrich_findings, synthesize_digest
from posthog.temporal.ai.pulse.selection import select_candidates
from posthog.temporal.ai.pulse.types import (
    CandidateMetric,
    DeliverDigestInputs,
    DetectChangesInputs,
    EnrichedFinding,
    EnrichFindingsInputs,
    Finding,
    SelectCandidatesInputs,
    SynthesizeDigestInputs,
)
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)


class PulseScanInputs(BaseModel):
    team_id: int
    period_key: str
    period_start: str
    period_end: str
    max_candidates: int = 200
    robust_z_threshold: float = 3.5
    min_change_pct: float = 0.25
    baseline_weeks: int = 4
    max_findings: int = 5
    user_id: int | None = None


class ScanConfig(BaseModel):
    """Detection config resolved from the team's PulseSubscription (with sensitivity presets applied)."""

    min_change_pct: float
    robust_z_threshold: float
    baseline_weeks: int
    max_findings: int


@activity.defn
async def load_scan_config_activity(team_id: int, defaults: ScanConfig) -> ScanConfig:
    """Resolve the team's detection config from its PulseSubscription, falling back to defaults."""

    @database_sync_to_async
    def _load() -> ScanConfig:
        with team_scope(team_id, canonical=True):
            subscription = PulseSubscription.objects.filter(team_id=team_id).first()
        if subscription is None:
            return defaults
        min_change_pct, robust_z_threshold = subscription.resolve_sensitivity()
        return ScanConfig(
            min_change_pct=min_change_pct,
            robust_z_threshold=robust_z_threshold,
            baseline_weeks=subscription.baseline_weeks,
            max_findings=subscription.max_findings,
        )

    return await _load()


@activity.defn
async def select_candidate_metrics_activity(inputs: SelectCandidatesInputs) -> list[CandidateMetric]:
    return await select_candidates(team_id=inputs.team_id, max_candidates=inputs.max_candidates)


@activity.defn
async def detect_changes_activity(inputs: DetectChangesInputs) -> list[Finding]:
    return await detect_changes(
        team_id=inputs.team_id,
        candidates=inputs.candidates,
        min_change_pct=inputs.min_change_pct,
        robust_z_threshold=inputs.robust_z_threshold,
    )


@activity.defn
async def enrich_findings_activity(inputs: EnrichFindingsInputs) -> list[EnrichedFinding]:
    return await enrich_findings(
        team_id=inputs.team_id,
        user_id=inputs.user_id,
        findings=inputs.findings,
        max_findings=inputs.max_findings,
        period_start=inputs.period_start,
        period_end=inputs.period_end,
    )


@activity.defn
async def persist_findings_activity(inputs: DeliverDigestInputs) -> list[str]:
    return await persist_findings(
        team_id=inputs.team_id,
        digest_id=inputs.digest_id,
        findings=inputs.findings,
    )


@activity.defn
async def notify_digest_activity(inputs: DeliverDigestInputs) -> None:
    """Fan out one in-app notification per team member. Idempotent across Temporal retries."""
    await notify_digest(
        team_id=inputs.team_id,
        digest_id=inputs.digest_id,
        findings=inputs.findings,
    )


@activity.defn
async def synthesize_digest_activity(inputs: SynthesizeDigestInputs) -> None:
    """Write the digest-level synthesis (big-picture across findings). Best-effort and additive."""
    summary = await synthesize_digest(
        team_id=inputs.team_id,
        user_id=inputs.user_id,
        findings=inputs.findings,
        period_start=inputs.period_start,
        period_end=inputs.period_end,
    )
    if not summary:
        return

    @database_sync_to_async
    def _set() -> None:
        with team_scope(inputs.team_id, canonical=True):
            PulseDigest.objects.filter(id=inputs.digest_id, team_id=inputs.team_id).update(summary=summary)

    await _set()


@activity.defn
async def create_or_get_digest_activity(team_id: int, period_key: str, period_start: str, period_end: str) -> str:
    """Find-or-create one PulseDigest per (team, period). Idempotent across re-runs and retries.

    `period_key` is the deterministic idempotency key (ISO week / date). The digest has no
    period_key column, so identity is matched on the persisted (period_start, period_end) bounds —
    deterministically derived from the same period, so they coincide with the key.
    """
    start = datetime.fromisoformat(period_start)
    end = datetime.fromisoformat(period_end)

    @database_sync_to_async
    def _create() -> str:
        with team_scope(team_id, canonical=True):
            existing = (
                PulseDigest.objects.filter(team_id=team_id, period_start=start, period_end=end)
                .order_by("created_at")
                .first()
            )
            if existing:
                return str(existing.id)
            digest = PulseDigest.objects.create(
                team_id=team_id,
                period_start=start,
                period_end=end,
                status=PulseDigestStatus.GENERATING,
            )
            return str(digest.id)

    return await _create()


@activity.defn
async def set_workflow_run_id_activity(team_id: int, digest_id: str, run_id: str) -> None:
    @database_sync_to_async
    def _set() -> None:
        with team_scope(team_id, canonical=True):
            PulseDigest.objects.filter(id=digest_id, team_id=team_id).update(workflow_run_id=run_id)

    await _set()


@activity.defn
async def set_digest_status_activity(team_id: int, digest_id: str, status: str, error: str | None = None) -> None:
    @database_sync_to_async
    def _set() -> None:
        with team_scope(team_id, canonical=True):
            digest = PulseDigest.objects.filter(id=digest_id, team_id=team_id).first()
            if not digest:
                return
            digest.status = status
            update_fields = ["status"]
            if error is not None:
                digest.error = {"message": error[:1000]}
                update_fields.append("error")
            digest.save(update_fields=update_fields)

    await _set()


@workflow.defn(name="pulse-scan")
class PulseScanWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PulseScanInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return PulseScanInputs.model_validate(loaded)

    @workflow.run
    async def run(self, inputs: PulseScanInputs) -> dict:
        retry_policy = common.RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_attempts=2,
        )

        digest_id = await workflow.execute_activity(
            create_or_get_digest_activity,
            args=[inputs.team_id, inputs.period_key, inputs.period_start, inputs.period_end],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        await workflow.execute_activity(
            set_workflow_run_id_activity,
            args=[inputs.team_id, digest_id, workflow.info().run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        config = await workflow.execute_activity(
            load_scan_config_activity,
            args=[
                inputs.team_id,
                ScanConfig(
                    min_change_pct=inputs.min_change_pct,
                    robust_z_threshold=inputs.robust_z_threshold,
                    baseline_weeks=inputs.baseline_weeks,
                    max_findings=inputs.max_findings,
                ),
            ],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        try:
            candidates = await workflow.execute_activity(
                select_candidate_metrics_activity,
                SelectCandidatesInputs(
                    team_id=inputs.team_id,
                    max_candidates=inputs.max_candidates,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            findings = await workflow.execute_activity(
                detect_changes_activity,
                DetectChangesInputs(
                    team_id=inputs.team_id,
                    candidates=candidates,
                    robust_z_threshold=config.robust_z_threshold,
                    min_change_pct=config.min_change_pct,
                ),
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            if not findings:
                await workflow.execute_activity(
                    set_digest_status_activity,
                    args=[inputs.team_id, digest_id, PulseDigestStatus.DELIVERED.value],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry_policy,
                )
                metrics.increment_scan_outcome("delivered")
                metrics.record_finding_count(0)
                return {"digest_id": digest_id, "finding_count": 0}

            enriched = await workflow.execute_activity(
                enrich_findings_activity,
                EnrichFindingsInputs(
                    team_id=inputs.team_id,
                    user_id=inputs.user_id,
                    findings=findings,
                    max_findings=config.max_findings,
                    period_start=inputs.period_start,
                    period_end=inputs.period_end,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            await workflow.execute_activity(
                persist_findings_activity,
                DeliverDigestInputs(
                    team_id=inputs.team_id,
                    digest_id=digest_id,
                    findings=enriched,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            # Digest-level synthesis (big-picture across findings). Best-effort: failure won't block delivery.
            await workflow.execute_activity(
                synthesize_digest_activity,
                SynthesizeDigestInputs(
                    team_id=inputs.team_id,
                    digest_id=digest_id,
                    user_id=inputs.user_id,
                    findings=enriched,
                    period_start=inputs.period_start,
                    period_end=inputs.period_end,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            # Notify AFTER persist so a rolled-back persist never produces orphan notifications.
            # The fan-out is idempotent per recipient, so a retry past this point is safe.
            await workflow.execute_activity(
                notify_digest_activity,
                DeliverDigestInputs(
                    team_id=inputs.team_id,
                    digest_id=digest_id,
                    findings=enriched,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            metrics.increment_scan_outcome("delivered")
            metrics.record_finding_count(len(enriched))
            return {"digest_id": digest_id, "finding_count": len(enriched)}
        except Exception as exc:
            await workflow.execute_activity(
                set_digest_status_activity,
                args=[inputs.team_id, digest_id, PulseDigestStatus.FAILED.value, str(exc)],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=1),
            )
            metrics.increment_scan_outcome("failed")
            raise
