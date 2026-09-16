from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from itertools import chain
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import asyncify

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.learning.contracts import EvidenceRef
from products.business_knowledge.backend.learning.providers import LearningEvidenceProvider, get_learning_providers
from products.business_knowledge.backend.models import (
    KnowledgeLearningRun,
    LearningRunStatus,
    TeamBusinessKnowledgeConfig,
)

from ..constants import (
    ANALYSIS_VERSION,
    LEARNING_COORDINATOR_INTERVAL_MINUTES,
    LEARNING_MAX_ITEMS_PER_TEAM,
    LEARNING_MAX_ITEMS_PER_TICK,
    LEARNING_MAX_LOOKBACK_DAYS,
    LEARNING_PROVIDER_MAX_SCAN_LIMIT,
    LEARNING_PROVIDER_SCAN_LIMIT,
    LEARNING_RETRY_BACKOFF_MINUTES,
    LEARNING_RUNNING_STALE_MINUTES,
    LEARNING_SETTLE_MINUTES,
)
from ..schemas import CollectLearningEvidenceOutput, LearningCoordinatorInput, LearningWorkItem

logger = structlog.get_logger(__name__)


@frozen
class _EvidenceIdentity:
    provider: str
    evidence_key: str


def _canonical_teams(input: LearningCoordinatorInput, now: datetime) -> Iterable[tuple[Team, int | None]]:
    if input.team_id is None:
        configs = (
            TeamBusinessKnowledgeConfig.objects.filter(
                learn_from_support_enabled=True, team__parent_team_id__isnull=True
            )
            .select_related("team__organization")
            .order_by("team_id")
        )
        config_count = configs.count()
        if config_count == 0:
            return
        tick = int(now.timestamp()) // (LEARNING_COORDINATOR_INTERVAL_MINUTES * 60)
        start = tick % config_count
        rotated_configs = chain(
            configs[start:].iterator(chunk_size=100),
            configs[:start].iterator(chunk_size=100),
        )
        for config in rotated_configs:
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


def _existing_runs(canonical_team_id: int, refs: list[EvidenceRef]) -> dict[_EvidenceIdentity, KnowledgeLearningRun]:
    if not refs:
        return {}
    providers = {ref.provider for ref in refs}
    evidence_keys = {ref.evidence_key for ref in refs}
    runs = KnowledgeLearningRun.objects.for_team(canonical_team_id).filter(
        analysis_version=ANALYSIS_VERSION,
        provider__in=providers,
        evidence_key__in=evidence_keys,
    )
    return {_EvidenceIdentity(provider=run.provider, evidence_key=run.evidence_key): run for run in runs}


def _run_can_start(run: KnowledgeLearningRun, ref: EvidenceRef, now: datetime) -> bool:
    if run.source_team_id != ref.source_team_id or run.status == LearningRunStatus.COMPLETED:
        return False
    stale_minutes = (
        LEARNING_RUNNING_STALE_MINUTES if run.status == LearningRunStatus.RUNNING else LEARNING_RETRY_BACKOFF_MINUTES
    )
    return run.updated_at <= now - timedelta(minutes=stale_minutes)


def _claim_existing_run(run: KnowledgeLearningRun, now: datetime) -> bool:
    claimed = (
        KnowledgeLearningRun.objects.for_team(run.team_id)
        .filter(id=run.id, status=run.status, updated_at=run.updated_at)
        .update(updated_at=now)
    )
    return claimed == 1


def _create_run(canonical_team: Team, ref: EvidenceRef) -> tuple[KnowledgeLearningRun, bool]:
    lookup = {
        "provider": ref.provider,
        "evidence_key": ref.evidence_key,
        "analysis_version": ANALYSIS_VERSION,
    }
    try:
        with transaction.atomic():
            run, created = KnowledgeLearningRun.objects.for_team(canonical_team.id).get_or_create(
                **lookup,
                defaults={
                    "team": canonical_team,
                    "source_team_id": ref.source_team_id,
                },
            )
            return run, created
    except IntegrityError:
        return KnowledgeLearningRun.objects.for_team(canonical_team.id).get(**lookup), False


def _valid_page_refs(
    collected: list[EvidenceRef],
    *,
    canonical_team_id: int,
    source_team_id: int,
    provider_name: str,
    settle_cutoff: datetime,
    ticket_id: UUID | None,
    seen: set[_EvidenceIdentity],
) -> list[EvidenceRef]:
    page_refs: list[EvidenceRef] = []
    for ref in collected:
        if ref.provider != provider_name or ref.source_team_id != source_team_id:
            logger.error(
                "business_knowledge.learning.invalid_evidence_ref",
                team_id=canonical_team_id,
                source_team_id=source_team_id,
                provider=provider_name,
            )
            continue
        if ref.revision_at > settle_cutoff:
            continue
        identity = _EvidenceIdentity(provider=ref.provider, evidence_key=ref.evidence_key)
        if identity in seen or (ticket_id is not None and ref.ticket_id != ticket_id):
            continue
        seen.add(identity)
        page_refs.append(ref)
    return page_refs


def _collect_provider_refs(
    canonical_team: Team,
    *,
    source_team_id: int,
    provider: LearningEvidenceProvider,
    since: datetime,
    settle_cutoff: datetime,
    ticket_id: UUID | None,
    now: datetime,
    seen: set[_EvidenceIdentity],
    limit: int,
) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    offset = 0
    while offset < LEARNING_PROVIDER_MAX_SCAN_LIMIT:
        page_limit = min(
            LEARNING_PROVIDER_SCAN_LIMIT,
            LEARNING_PROVIDER_MAX_SCAN_LIMIT - offset,
        )
        try:
            collected = provider.collect(
                source_team_id,
                since=since,
                limit=page_limit,
                offset=offset,
                ticket_id=ticket_id,
            )
        except Exception:
            logger.exception(
                "business_knowledge.learning.collection_failed",
                team_id=canonical_team.id,
                source_team_id=source_team_id,
                provider=provider.name,
            )
            break
        if not collected:
            break

        page_refs = _valid_page_refs(
            collected,
            canonical_team_id=canonical_team.id,
            source_team_id=source_team_id,
            provider_name=provider.name,
            settle_cutoff=settle_cutoff,
            ticket_id=ticket_id,
            seen=seen,
        )
        existing = _existing_runs(canonical_team.id, page_refs)
        for ref in page_refs:
            identity = _EvidenceIdentity(provider=ref.provider, evidence_key=ref.evidence_key)
            run = existing.get(identity)
            if run is not None and not _run_can_start(run, ref, now):
                continue
            refs.append(ref)
            if len(refs) >= limit:
                return refs

        offset += len(collected)
        if ticket_id is not None or len(collected) < page_limit:
            break
    return refs


def _collect_team_refs(
    canonical_team: Team,
    *,
    requested_source_team_id: int | None,
    since: datetime,
    settle_cutoff: datetime,
    ticket_id: UUID | None,
    now: datetime,
) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    seen: set[_EvidenceIdentity] = set()
    for source_team_id in _source_team_ids(canonical_team, requested_source_team_id):
        for provider in get_learning_providers():
            refs.extend(
                _collect_provider_refs(
                    canonical_team,
                    source_team_id=source_team_id,
                    provider=provider,
                    since=since,
                    settle_cutoff=settle_cutoff,
                    ticket_id=ticket_id,
                    now=now,
                    seen=seen,
                    limit=LEARNING_MAX_ITEMS_PER_TEAM - len(refs),
                )
            )
            if len(refs) >= LEARNING_MAX_ITEMS_PER_TEAM:
                return refs
    return refs


def collect_learning_evidence(input: LearningCoordinatorInput) -> CollectLearningEvidenceOutput:
    if input.lookback_days <= 0 or input.lookback_days > LEARNING_MAX_LOOKBACK_DAYS:
        raise ValueError(f"lookback_days must be between 1 and {LEARNING_MAX_LOOKBACK_DAYS}")
    ticket_id = UUID(input.ticket_id) if input.ticket_id is not None else None
    now = timezone.now()
    since = now - timedelta(days=input.lookback_days)
    settle_cutoff = now - timedelta(minutes=LEARNING_SETTLE_MINUTES)
    items: list[LearningWorkItem] = []

    for canonical_team, requested_source_team_id in _canonical_teams(input, now):
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
            now=now,
        )
        existing = _existing_runs(canonical_team.id, refs)
        selected_for_team = 0
        for ref in refs:
            if selected_for_team >= LEARNING_MAX_ITEMS_PER_TEAM or len(items) >= LEARNING_MAX_ITEMS_PER_TICK:
                break
            identity = _EvidenceIdentity(provider=ref.provider, evidence_key=ref.evidence_key)
            run = existing.get(identity)
            created = False
            if run is None:
                run, created = _create_run(canonical_team, ref)
                existing[identity] = run
            if not created and not _run_can_start(run, ref, now):
                continue
            if not created and not _claim_existing_run(run, now):
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
