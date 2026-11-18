"""How much the knowledge base is used, read from the citations support agent runs record."""

import datetime
from collections.abc import Sequence
from uuid import UUID

from django.db.models import Count, Max, QuerySet
from django.db.models.functions import TruncDate
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import resolve_effective_team_id

from .models import KnowledgeRunCitation, KnowledgeSource

USAGE_DEFAULT_DAYS = 30
USAGE_MAX_DAYS = 90
USAGE_TOP_SOURCES = 10


@frozen
class DailyCitedRuns:
    date: datetime.date
    cited_run_count: int


@frozen
class SourceUsage:
    source_id: UUID
    name: str
    is_generated: bool
    cited_run_count: int
    last_cited_at: datetime.datetime


@frozen
class KnowledgeUsage:
    days: int
    cited_run_count: int
    learned_cited_run_count: int
    source_count: int
    cited_source_count: int
    daily: list[DailyCitedRuns]
    top_sources: list[SourceUsage]


def _distinct_runs(citations: QuerySet[KnowledgeRunCitation]) -> int:
    return citations.values("run_id").distinct().count()


def _knowledge_usage(team_id: int, *, days: int) -> KnowledgeUsage:
    today = timezone.now().date()
    first_day = today - datetime.timedelta(days=days - 1)
    since = datetime.datetime.combine(first_day, datetime.time.min, tzinfo=datetime.UTC)
    sources = KnowledgeSource.objects.filter(team_id=team_id)
    # A deleted source keeps its citation rows, so every count below reads only the sources that still exist.
    citations = KnowledgeRunCitation.objects.filter(
        team_id=team_id, created_at__gte=since, source_id__in=sources.values("id")
    )

    runs_by_day = dict(
        citations.annotate(day=TruncDate("created_at", tzinfo=datetime.UTC))
        .values("day")
        .annotate(runs=Count("run_id", distinct=True))
        .values_list("day", "runs")
    )
    top = list(
        citations.values("source_id")
        .annotate(runs=Count("run_id", distinct=True), last_cited_at=Max("created_at"))
        .order_by("-runs", "-last_cited_at", "source_id")[:USAGE_TOP_SOURCES]
    )
    top_sources_by_id = {
        source.id: source
        for source in sources.filter(id__in=[row["source_id"] for row in top]).only("id", "name", "is_generated")
    }

    return KnowledgeUsage(
        days=days,
        cited_run_count=_distinct_runs(citations),
        learned_cited_run_count=_distinct_runs(
            citations.filter(source_id__in=sources.filter(is_generated=True).values("id"))
        ),
        source_count=sources.count(),
        cited_source_count=citations.values("source_id").distinct().count(),
        daily=[
            DailyCitedRuns(date=day, cited_run_count=runs_by_day.get(day, 0))
            for day in (first_day + datetime.timedelta(days=offset) for offset in range(days))
        ],
        top_sources=[
            SourceUsage(
                source_id=row["source_id"],
                name=top_sources_by_id[row["source_id"]].name,
                is_generated=top_sources_by_id[row["source_id"]].is_generated,
                cited_run_count=row["runs"],
                last_cited_at=row["last_cited_at"],
            )
            for row in top
            if row["source_id"] in top_sources_by_id
        ],
    )


def knowledge_usage(team_id: int, *, days: int = USAGE_DEFAULT_DAYS) -> KnowledgeUsage:
    """Usage of the team's knowledge over the last ``days`` days, today included."""
    # Knowledge rows live under the parent team, and a child environment can ask for them.
    canonical_team_id = resolve_effective_team_id(team_id)
    with team_scope(canonical_team_id, canonical=True):
        return _knowledge_usage(canonical_team_id, days=days)


def attach_source_citations(team_id: int, sources: Sequence[KnowledgeSource]) -> None:
    """Set the citation totals the source serializer reads, for these sources only.

    The source list is polled while a source ingests, so it must not aggregate the
    citation history of every source in the project on each request.
    """
    if not sources:
        return
    canonical_team_id = resolve_effective_team_id(team_id)
    with team_scope(canonical_team_id, canonical=True):
        totals = {
            row["source_id"]: row
            for row in KnowledgeRunCitation.objects.filter(
                team_id=canonical_team_id, source_id__in=[source.id for source in sources]
            )
            .values("source_id")
            .annotate(runs=Count("run_id", distinct=True), last_cited_at=Max("created_at"))
        }
    for source in sources:
        row = totals.get(source.id)
        source._cited_run_count = row["runs"] if row else 0  # type: ignore[attr-defined]
        source._last_cited_at = row["last_cited_at"] if row else None  # type: ignore[attr-defined]
