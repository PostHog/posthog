from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import asyncify

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.learning.contracts import EvidenceRef
from products.business_knowledge.backend.learning.providers import get_learning_providers
from products.business_knowledge.backend.models import (
    KnowledgeLearningRun,
    LearningRunStatus,
    TeamBusinessKnowledgeConfig,
)

from ..constants import (
    ANALYSIS_VERSION,
    LEARNING_MAX_ITEMS_PER_TEAM,
    LEARNING_MAX_ITEMS_PER_TICK,
    LEARNING_MAX_LOOKBACK_DAYS,
    LEARNING_PROVIDER_MAX_SCAN_LIMIT,
    LEARNING_PROVIDER_SCAN_LIMIT,
    LEARNING_SETTLE_MINUTES,
)
from ..schemas import CollectLearningEvidenceOutput, LearningCoordinatorInput, LearningWorkItem

logger = structlog.get_logger(__name__)


def _canonical_teams(input: LearningCoordinatorInput) -> Iterable[tuple[Team, int | None]]:
    if input.team_id is None:
        configs = (
            TeamBusinessKnowledgeConfig.objects.filter(
                learn_from_support_enabled=True, team__parent_team_id__isnull=True
            )
            .select_related("team__organization")
            .order_by("team_id")
        )
        for config in configs.iterator(chunk_size=100):
            yield config.team, None
        return

    requested_team = Team.objects.select_related("organization").get(pk=input.team_id)
    canonical_team_id = requested_team.parent_team_id or requested_team.id
    selected_config = (
        TeamBusinessKnowledgeConfig.objects.filter(
            team_id=canonical_team_id,
            learn_from_support_enabled=True,
        )
        .select_related("team__organization")
        .first()
    )
    if selected_config is None:
        return
    source_team_id = requested_team.id if requested_team.parent_team_id else None
    yield selected_config.team, source_team_id


def _source_team_ids(canonical_team: Team, requested_source_team_id: int | None) -> list[int]:
    if requested_source_team_id is not None:
        return list(
            Team.objects.filter(
                Q(id=canonical_team.id) | Q(parent_team_id=canonical_team.id),
                id=requested_source_team_id,
                conversations_enabled=True,
            ).values_list("id", flat=True)
        )
    return list(
        Team.objects.filter(
            Q(id=canonical_team.id) | Q(parent_team_id=canonical_team.id),
            conversations_enabled=True,
        )
        .order_by("id")
        .values_list("id", flat=True)
    )


def _existing_runs(canonical_team_id: int, refs: list[EvidenceRef]) -> dict[tuple[str, str], KnowledgeLearningRun]:
    if not refs:
        return {}
    providers = {ref.provider for ref in refs}
    evidence_keys = {ref.evidence_key for ref in refs}
    runs = KnowledgeLearningRun.objects.for_team(canonical_team_id).filter(
        analysis_version=ANALYSIS_VERSION,
        provider__in=providers,
        evidence_key__in=evidence_keys,
    )
    return {(run.provider, run.evidence_key): run for run in runs}


def _provider_scan_limit(canonical_team_id: int, source_team_id: int, provider: str, since: datetime) -> int:
    completed_count = (
        KnowledgeLearningRun.objects.for_team(canonical_team_id)
        .filter(
            provider=provider,
            source_team_id=source_team_id,
            analysis_version=ANALYSIS_VERSION,
            status=LearningRunStatus.COMPLETED,
            created_at__gte=since,
        )
        .count()
    )
    return min(LEARNING_PROVIDER_SCAN_LIMIT + completed_count, LEARNING_PROVIDER_MAX_SCAN_LIMIT)


def _create_run(canonical_team: Team, ref: EvidenceRef) -> KnowledgeLearningRun:
    lookup = {
        "provider": ref.provider,
        "evidence_key": ref.evidence_key,
        "analysis_version": ANALYSIS_VERSION,
    }
    try:
        with transaction.atomic():
            run, _ = KnowledgeLearningRun.objects.for_team(canonical_team.id).get_or_create(
                **lookup,
                defaults={
                    "team": canonical_team,
                    "source_team_id": ref.source_team_id,
                },
            )
            return run
    except IntegrityError:
        return KnowledgeLearningRun.objects.for_team(canonical_team.id).get(**lookup)


def _collect_team_refs(
    canonical_team: Team,
    *,
    requested_source_team_id: int | None,
    since: datetime,
    settle_cutoff: datetime,
    ticket_id: UUID | None,
) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    seen: set[tuple[str, str]] = set()
    for source_team_id in _source_team_ids(canonical_team, requested_source_team_id):
        for provider in get_learning_providers():
            try:
                collected = provider.collect(
                    source_team_id,
                    since=since,
                    limit=_provider_scan_limit(canonical_team.id, source_team_id, provider.name, since),
                )
            except Exception:
                logger.exception(
                    "business_knowledge.learning.collection_failed",
                    team_id=canonical_team.id,
                    source_team_id=source_team_id,
                    provider=provider.name,
                )
                continue
            for ref in collected:
                if ref.provider != provider.name or ref.source_team_id != source_team_id:
                    logger.error(
                        "business_knowledge.learning.invalid_evidence_ref",
                        team_id=canonical_team.id,
                        source_team_id=source_team_id,
                        provider=provider.name,
                    )
                    continue
                if ref.revision_at > settle_cutoff:
                    continue
                identity = (ref.provider, ref.evidence_key)
                if identity in seen or (ticket_id is not None and ref.ticket_id != ticket_id):
                    continue
                seen.add(identity)
                refs.append(ref)
    return refs


def collect_learning_evidence(input: LearningCoordinatorInput) -> CollectLearningEvidenceOutput:
    if input.lookback_days <= 0 or input.lookback_days > LEARNING_MAX_LOOKBACK_DAYS:
        raise ValueError(f"lookback_days must be between 1 and {LEARNING_MAX_LOOKBACK_DAYS}")
    ticket_id = UUID(input.ticket_id) if input.ticket_id is not None else None
    now = timezone.now()
    since = now - timedelta(days=input.lookback_days)
    settle_cutoff = now - timedelta(minutes=LEARNING_SETTLE_MINUTES)
    items: list[LearningWorkItem] = []

    for canonical_team, requested_source_team_id in _canonical_teams(input):
        if len(items) >= LEARNING_MAX_ITEMS_PER_TICK:
            break
        if not canonical_team.organization.is_ai_data_processing_approved or not logic.has_feature_flag(canonical_team):
            continue

        refs = _collect_team_refs(
            canonical_team,
            requested_source_team_id=requested_source_team_id,
            since=since,
            settle_cutoff=settle_cutoff,
            ticket_id=ticket_id,
        )
        existing = _existing_runs(canonical_team.id, refs)
        selected_for_team = 0
        for ref in refs:
            if selected_for_team >= LEARNING_MAX_ITEMS_PER_TEAM or len(items) >= LEARNING_MAX_ITEMS_PER_TICK:
                break
            identity = (ref.provider, ref.evidence_key)
            run = existing.get(identity)
            if run is None:
                run = _create_run(canonical_team, ref)
                existing[identity] = run
            if run.status == LearningRunStatus.COMPLETED or run.source_team_id != ref.source_team_id:
                continue
            items.append(
                LearningWorkItem(
                    team_id=canonical_team.id,
                    run_id=str(run.id),
                    evidence=ref,
                )
            )
            selected_for_team += 1

    logger.info("business_knowledge.learning.collection_completed", eligible_count=len(items))
    return CollectLearningEvidenceOutput(items=items)


@activity.defn
@asyncify
def collect_learning_evidence_activity(input: LearningCoordinatorInput) -> CollectLearningEvidenceOutput:
    with HeartbeaterSync(logger=logger):
        return collect_learning_evidence(input)
