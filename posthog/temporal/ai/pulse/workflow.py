"""PulseScanWorkflow — orchestrates proactive insight scans for one team."""

import json
from datetime import UTC, datetime, timedelta

import structlog
import temporalio.common
import temporalio.activity
import temporalio.workflow
from pydantic import BaseModel

from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.delivery import deliver_digest
from posthog.temporal.ai.pulse.detection import detect_changes
from posthog.temporal.ai.pulse.narrative import enrich_findings
from posthog.temporal.ai.pulse.selection import select_candidates
from posthog.temporal.ai.pulse.types import (
    CandidateMetric,
    DeliverDigestInputs,
    DetectChangesInputs,
    EnrichedFinding,
    EnrichFindingsInputs,
    Finding,
    SelectCandidatesInputs,
)
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)


class PulseScanInputs(BaseModel):
    team_id: int
    digest_id: str | None = None
    max_candidates: int = 50
    z_threshold: float = 2.0
    min_change_pct: float = 0.25
    max_findings: int = 5


@temporalio.activity.defn
async def select_candidate_metrics_activity(inputs: SelectCandidatesInputs) -> list[CandidateMetric]:
    return await select_candidates(team_id=inputs.team_id, max_candidates=inputs.max_candidates)


@temporalio.activity.defn
async def detect_changes_activity(inputs: DetectChangesInputs) -> list[Finding]:
    return await detect_changes(
        team_id=inputs.team_id,
        candidates=inputs.candidates,
        z_threshold=inputs.z_threshold,
        min_change_pct=inputs.min_change_pct,
    )


@temporalio.activity.defn
async def enrich_findings_activity(inputs: EnrichFindingsInputs) -> list[EnrichedFinding]:
    return await enrich_findings(
        team_id=inputs.team_id,
        findings=inputs.findings,
        max_findings=inputs.max_findings,
    )


@temporalio.activity.defn
async def deliver_digest_activity(inputs: DeliverDigestInputs) -> list[str]:
    return await deliver_digest(
        team_id=inputs.team_id,
        digest_id=inputs.digest_id,
        findings=inputs.findings,
    )


@temporalio.activity.defn
async def create_or_get_digest_activity(team_id: int, digest_id: str | None) -> str:
    """Create a new PulseDigest row for this scan, or reuse the provided one."""
    from posthog.models import PulseDigest
    from posthog.models.pulse import PulseDigestStatus

    @database_sync_to_async
    def _create() -> str:
        if digest_id:
            existing = PulseDigest.objects.filter(id=digest_id, team_id=team_id).first()
            if existing:
                return str(existing.id)
        now = datetime.now(UTC)
        digest = PulseDigest.objects.create(
            team_id=team_id,
            period_start=now - timedelta(days=7),
            period_end=now,
            status=PulseDigestStatus.GENERATING,
        )
        return str(digest.id)

    return await _create()


@temporalio.activity.defn
async def set_digest_status_activity(digest_id: str, status: str, error: str | None = None) -> None:
    from posthog.models import PulseDigest

    @database_sync_to_async
    def _set() -> None:
        digest = PulseDigest.objects.filter(id=digest_id).first()
        if not digest:
            return
        digest.status = status
        update_fields = ["status"]
        if error is not None:
            digest.error = {"message": error[:1000]}
            update_fields.append("error")
        digest.save(update_fields=update_fields)

    await _set()


@temporalio.workflow.defn(name="pulse-scan")
class PulseScanWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PulseScanInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return PulseScanInputs.model_validate(loaded)

    @temporalio.workflow.run
    async def run(self, inputs: PulseScanInputs) -> dict:
        from posthog.models.pulse import PulseDigestStatus

        retry_policy = temporalio.common.RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_attempts=2,
        )

        digest_id = await temporalio.workflow.execute_activity(
            create_or_get_digest_activity,
            args=[inputs.team_id, inputs.digest_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        try:
            candidates = await temporalio.workflow.execute_activity(
                select_candidate_metrics_activity,
                SelectCandidatesInputs(
                    team_id=inputs.team_id,
                    max_candidates=inputs.max_candidates,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            findings = await temporalio.workflow.execute_activity(
                detect_changes_activity,
                DetectChangesInputs(
                    team_id=inputs.team_id,
                    candidates=candidates,
                    z_threshold=inputs.z_threshold,
                    min_change_pct=inputs.min_change_pct,
                ),
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            if not findings:
                await temporalio.workflow.execute_activity(
                    set_digest_status_activity,
                    args=[digest_id, PulseDigestStatus.DELIVERED.value],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry_policy,
                )
                return {"digest_id": digest_id, "finding_count": 0}

            enriched = await temporalio.workflow.execute_activity(
                enrich_findings_activity,
                EnrichFindingsInputs(
                    team_id=inputs.team_id,
                    findings=findings,
                    max_findings=inputs.max_findings,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            await temporalio.workflow.execute_activity(
                deliver_digest_activity,
                DeliverDigestInputs(
                    team_id=inputs.team_id,
                    digest_id=digest_id,
                    findings=enriched,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

            return {"digest_id": digest_id, "finding_count": len(enriched)}
        except Exception as exc:
            await temporalio.workflow.execute_activity(
                set_digest_status_activity,
                args=[digest_id, PulseDigestStatus.FAILED.value, str(exc)],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
            )
            raise
