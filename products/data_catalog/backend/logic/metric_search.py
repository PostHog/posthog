"""Ranked catalog search over a team's metrics.

Postgres full-text search over weighted metric fields, exact and acronym matches on names, and a
trigram fallback for typos. Every hit carries the reason it matched, and the result says whether any
hit is a confident match.
"""

import re
from collections.abc import Sequence
from enum import IntEnum
from functools import reduce
from operator import or_
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    SearchVectorField,
    TrigramWordSimilarity,
)
from django.db.models import BooleanField, Case, Expression, Func, Q, QuerySet, Value, When
from django.db.models.expressions import CombinedExpression
from django.db.models.functions import Coalesce, Greatest

from posthog.dataclasses import frozen
from posthog.models import Team, User

from ..facade.enums import MetricStatus
from ..models import Metric
from .analytics import capture_metric_search_event

if TYPE_CHECKING:
    from rest_framework.request import Request

MAX_SEARCH_PHRASINGS = 5
MAX_SEARCH_PHRASING_LENGTH = 200
SEARCH_DEFAULT_LIMIT = 10
SEARCH_MAX_LIMIT = 50

# A hit scores 1 / (RRF_K + its rank), the scale of reciprocal rank fusion.
RRF_K = 60

# word_similarity of a misspelled word against the closest word in a name. "retension" scores about
# 0.5 against "retention".
TRIGRAM_MIN_WORD_SIMILARITY = 0.45

_ACRONYM_MAX_LENGTH = 6
_WORD_RE = re.compile(r"[a-z0-9]+")


class MatchTier(IntEnum):
    """How strongly a lexical hit matches. A higher tier always ranks above a lower one."""

    SOME_WORDS = 1
    TYPO = 2
    ALL_WORDS = 3
    ACRONYM = 4
    NAME = 5


# A lexical hit at this tier or above means the catalog holds a metric for the query.
CONFIDENT_TIER = MatchTier.ALL_WORDS


@frozen
class MetricSearchHit:
    metric: Metric
    score: float
    match_reason: str


@frozen
class MetricSearchResult:
    hits: list[MetricSearchHit]
    confident_match: bool
    search_mode: str


@frozen
class _LexicalMatch:
    tier: MatchTier
    rank: float
    reason: str


def normalize_phrasings(queries: Sequence[str]) -> list[str]:
    """Strip, drop blanks and duplicates, and cap the count and the length of each phrasing."""
    seen: dict[str, None] = {}
    for query in queries:
        phrasing = " ".join(query.split())[:MAX_SEARCH_PHRASING_LENGTH]
        if phrasing and phrasing.lower() not in {key.lower() for key in seen}:
            seen[phrasing] = None
    return list(seen)[:MAX_SEARCH_PHRASINGS]


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _squash(text: str) -> str:
    return " ".join(_words(text))


def _acronym(text: str) -> str:
    words = _words(text)
    return "".join(word[0] for word in words) if len(words) >= 2 else ""


def _concat(*vectors: Expression) -> Expression:
    """Join tsvectors with ``||``. ``SearchVector.__add__`` refuses the definition vector, a plain ``Func``."""
    return reduce(lambda left, right: CombinedExpression(left, "||", right, output_field=SearchVectorField()), vectors)


def _definition_vector() -> Func:
    definition = Func(
        Value("english"),
        "definition",
        Value('["string"]'),
        function="jsonb_to_tsvector",
        output_field=SearchVectorField(),
    )
    return Func(
        Coalesce(definition, Value("", output_field=SearchVectorField())),
        Value("D"),
        function="setweight",
        output_field=SearchVectorField(),
    )


def _exact_matches(candidates: list[tuple[UUID, str, str]], phrasing: str) -> dict[UUID, _LexicalMatch]:
    """Name and acronym matches, decided in Python over the team's candidate names."""
    squashed = _squash(phrasing)
    compact = squashed.replace(" ", "")
    matches: dict[UUID, _LexicalMatch] = {}
    for metric_id, name, display_name in candidates:
        if squashed in (_squash(name), _squash(display_name)):
            matches[metric_id] = _LexicalMatch(tier=MatchTier.NAME, rank=1.0, reason="name match")
            continue
        if " " not in squashed and 2 <= len(compact) <= _ACRONYM_MAX_LENGTH:
            if compact in (_acronym(name), _acronym(display_name)):
                matches[metric_id] = _LexicalMatch(tier=MatchTier.ACRONYM, rank=1.0, reason="acronym of the name")
    return matches


def _full_text_matches(candidates: QuerySet[Metric], phrasing: str) -> dict[UUID, _LexicalMatch]:
    """Weighted full-text matches. All words must match for the ALL_WORDS tier; any word earns SOME_WORDS."""
    words = _words(phrasing)
    if not words:
        return {}
    all_words = SearchQuery(phrasing, search_type="websearch", config="english")
    any_word = reduce(or_, [SearchQuery(word, search_type="plain", config="english") for word in words])

    name_vector = SearchVector("name", "display_name", weight="A", config="english")
    description_vector = SearchVector("description", weight="C", config="english")
    text_vector = _concat(name_vector, description_vector)
    full_vector = _concat(text_vector, _definition_vector())

    def matched(vector_alias: str, query: SearchQuery) -> Case:
        return Case(
            When(Q(**{vector_alias: query}), then=Value(True)), default=Value(False), output_field=BooleanField()
        )

    rows = (
        candidates.alias(
            _text=text_vector,
            _full=full_vector,
            _name=name_vector,
            _description=description_vector,
        )
        .filter(Q(_text=any_word) | Q(_full=all_words))
        .annotate(
            _rank=SearchRank(full_vector, any_word),
            _all_text=matched("_text", all_words),
            _hit_name=matched("_name", any_word),
            _hit_description=matched("_description", any_word),
        )
        .values("id", "_rank", "_all_text", "_hit_name", "_hit_description")
    )

    matches: dict[UUID, _LexicalMatch] = {}
    for row in rows:
        if row["_hit_name"]:
            reason = "name match"
        elif row["_hit_description"]:
            reason = "description match"
        else:
            reason = "definition match"
        # A match only inside the query definition (a table or column name) never counts as all words.
        tier = MatchTier.ALL_WORDS if row["_all_text"] else MatchTier.SOME_WORDS
        matches[row["id"]] = _LexicalMatch(tier=tier, rank=float(row["_rank"]), reason=reason)
    return matches


def _typo_matches(candidates: QuerySet[Metric], phrasing: str) -> dict[UUID, _LexicalMatch]:
    if not _words(phrasing):
        return {}
    rows = (
        candidates.annotate(
            _similarity=Greatest(
                TrigramWordSimilarity(phrasing, "name"),
                TrigramWordSimilarity(phrasing, "display_name"),
            )
        )
        .filter(_similarity__gte=TRIGRAM_MIN_WORD_SIMILARITY)
        .values_list("id", "_similarity")
    )
    return {
        metric_id: _LexicalMatch(tier=MatchTier.TYPO, rank=float(similarity), reason="similar spelling to the name")
        for metric_id, similarity in rows
    }


def _better(current: _LexicalMatch | None, candidate: _LexicalMatch) -> bool:
    return current is None or (candidate.tier, candidate.rank) > (current.tier, current.rank)


def _lexical_lane(candidates: QuerySet[Metric], phrasings: list[str]) -> dict[UUID, _LexicalMatch]:
    """Best lexical match per metric across every phrasing."""
    names = list(candidates.values_list("id", "name", "display_name"))
    best: dict[UUID, _LexicalMatch] = {}
    for phrasing in phrasings:
        for lane in (
            _exact_matches(names, phrasing),
            _full_text_matches(candidates, phrasing),
            _typo_matches(candidates, phrasing),
        ):
            for metric_id, match in lane.items():
                if _better(best.get(metric_id), match):
                    best[metric_id] = match
    return best


def search_metrics(
    candidates: QuerySet[Metric],
    queries: Sequence[str],
    *,
    status: str | None = None,
    limit: int = SEARCH_DEFAULT_LIMIT,
) -> MetricSearchResult:
    """Rank ``candidates`` against one or more phrasings of the same need.

    ``candidates`` must already be the metrics the caller may see.
    """
    phrasings = normalize_phrasings(queries)
    limit = max(1, min(limit, SEARCH_MAX_LIMIT))
    if status:
        candidates = candidates.filter(status=status)
    if not phrasings:
        return MetricSearchResult(hits=[], confident_match=False, search_mode="lexical")

    lexical = _lexical_lane(candidates, phrasings)
    metrics = {metric.id: metric for metric in candidates.filter(id__in=set(lexical)).select_related("owner")}
    approved = {metric_id for metric_id, metric in metrics.items() if metric.status == MetricStatus.APPROVED}

    def lexical_order(metric_id: UUID) -> tuple[int, bool, float, str]:
        match = lexical[metric_id]
        return (-match.tier, metric_id not in approved, -match.rank, metrics[metric_id].name)

    ranked = sorted((metric_id for metric_id in lexical if metric_id in metrics), key=lexical_order)
    hits = [
        MetricSearchHit(
            metric=metrics[metric_id],
            score=round(1.0 / (RRF_K + position), 6),
            match_reason=lexical[metric_id].reason,
        )
        for position, metric_id in enumerate(ranked[:limit], start=1)
    ]
    confident = any(match.tier >= CONFIDENT_TIER for match in lexical.values())
    return MetricSearchResult(hits=hits, confident_match=confident, search_mode="lexical")


def search_catalog(
    team: Team,
    candidates: QuerySet[Metric],
    queries: Sequence[str],
    *,
    user: User | None,
    status: str | None = None,
    limit: int = SEARCH_DEFAULT_LIMIT,
    request: "Request | None" = None,
) -> MetricSearchResult:
    """Search the metrics the caller may see, and record the search without its text."""
    result = search_metrics(candidates, queries, status=status, limit=limit)
    top = result.hits[0] if result.hits else None
    capture_metric_search_event(
        team=team,
        user=user,
        phrasing_count=len(normalize_phrasings(queries)),
        result_count=len(result.hits),
        confident_match=result.confident_match,
        search_mode=result.search_mode,
        top_metric_name=top.metric.name if top else None,
        top_match_reason=top.match_reason if top else None,
        request=request,
    )
    return result
