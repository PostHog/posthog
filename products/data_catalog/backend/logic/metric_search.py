"""Ranked catalog search over a team's metrics, behind the ``search`` parameter of the metric list.

Postgres full-text search over weighted metric fields, exact and acronym matches on names, and a
trigram fallback for typos. Every hit carries the reason it matched, and the result says whether any
hit is a confident match.
"""

import re
from collections.abc import Sequence
from enum import IntEnum, StrEnum
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
from django.db.models.functions import Coalesce, Greatest, Least

from posthog.dataclasses import frozen
from posthog.helpers.trigram_search import normalize_search_term
from posthog.models import Team, User

from ..facade.contracts import MetricListFilters
from ..facade.enums import MetricStatus
from ..models import Metric
from .analytics import AnalyticsProps, capture_metric_search_event
from .metrics import metrics_visible_to_user

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

MAX_SEARCH_PHRASINGS = 5
MAX_SEARCH_PHRASING_LENGTH = 200
# A search answers with a short ranked page unless the caller asks for more.
SEARCH_DEFAULT_LIMIT = 10

# word_similarity of a misspelled word against the closest word in a name. "retension" scores about
# 0.5 against "retention". Every word of a phrasing must reach it, so one correct word does not carry
# the others.
TRIGRAM_MIN_WORD_SIMILARITY = 0.45
# Shorter words, such as "of", share too few trigrams with any name to count for or against a typo match.
_TYPO_MIN_WORD_LENGTH = 3

_ACRONYM_MAX_LENGTH = 6
_WORD_RE = re.compile(r"[a-z0-9]+")


class SearchMode(StrEnum):
    LEXICAL = "lexical"


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
    match_reason: str


@frozen
class MetricSearchResult:
    """One page of ranked hits. ``total`` counts the hits on every page."""

    hits: list[MetricSearchHit]
    total: int
    confident_match: bool
    search_mode: SearchMode


@frozen
class _LexicalMatch:
    tier: MatchTier
    rank: float
    reason: str


def normalize_phrasings(queries: Sequence[str]) -> list[str]:
    """Strip, drop blanks and duplicates, and cap the count and the length of each phrasing."""
    phrasings: list[str] = []
    seen: set[str] = set()
    for query in queries:
        phrasing = " ".join(normalize_search_term(query).split())[:MAX_SEARCH_PHRASING_LENGTH]
        if phrasing and phrasing.lower() not in seen:
            phrasings.append(phrasing)
            seen.add(phrasing.lower())
            # Stop at the cap, so a long comma list costs no more than its first few phrasings.
            if len(phrasings) == MAX_SEARCH_PHRASINGS:
                break
    return phrasings


def split_search(search: str) -> list[str]:
    """Phrasings in a metric list ``search``: commas separate alternative phrasings of one need."""
    return normalize_phrasings(search.split(","))


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
    if not squashed:
        return {}
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
    # A plain query ANDs the words, so operators a person typed, such as a leading "-", never exclude one.
    all_words = SearchQuery(" ".join(words), search_type="plain", config="english")
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
            _all_name=matched("_name", all_words),
            _all_description=matched("_description", all_words),
            _hit_name=matched("_name", any_word),
            _hit_description=matched("_description", any_word),
        )
        .values("id", "_rank", "_all_text", "_all_name", "_all_description", "_hit_name", "_hit_description")
    )

    matches: dict[UUID, _LexicalMatch] = {}
    for row in rows:
        # A match only inside the query definition (a table or column name) never counts as all words.
        if row["_all_text"]:
            place = "name" if row["_all_name"] else "description" if row["_all_description"] else "name and description"
            tier, reason = MatchTier.ALL_WORDS, f"all words in the {place}"
        else:
            place = "name" if row["_hit_name"] else "description" if row["_hit_description"] else "definition"
            tier, reason = MatchTier.SOME_WORDS, f"some words in the {place}"
        matches[row["id"]] = _LexicalMatch(tier=tier, rank=float(row["_rank"]), reason=reason)
    return matches


def _typo_matches(candidates: QuerySet[Metric], phrasing: str) -> dict[UUID, _LexicalMatch]:
    """Names that hold every word of the phrasing, allowing for spelling. The weakest word sets the score."""
    words = [word for word in _words(phrasing) if len(word) >= _TYPO_MIN_WORD_LENGTH]
    if not words:
        return {}
    per_word = [
        Greatest(TrigramWordSimilarity(word, "name"), TrigramWordSimilarity(word, "display_name")) for word in words
    ]
    rows = (
        candidates.annotate(_similarity=Least(*per_word) if len(per_word) > 1 else per_word[0])
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
    limit: int = SEARCH_DEFAULT_LIMIT,
    offset: int = 0,
) -> MetricSearchResult:
    """Rank ``candidates`` against one or more phrasings of the same need, and load one page of hits.

    ``candidates`` must already be the metrics the caller may see.
    """
    phrasings = normalize_phrasings(queries)
    if not phrasings:
        return MetricSearchResult(hits=[], total=0, confident_match=False, search_mode=SearchMode.LEXICAL)

    lexical = _lexical_lane(candidates, phrasings)
    # Rank on light rows, then load full metrics only for the hits that are returned.
    rows = {
        metric_id: (name, status)
        for metric_id, name, status in candidates.filter(id__in=set(lexical)).values_list("id", "name", "status")
    }
    # Inside one tier an approved metric ranks first, because approval says more than the text rank.
    ranked = sorted(
        rows,
        key=lambda metric_id: (
            -lexical[metric_id].tier,
            rows[metric_id][1] != MetricStatus.APPROVED,
            -lexical[metric_id].rank,
            rows[metric_id][0],
        ),
    )
    page = ranked[offset : offset + limit]
    metrics = {metric.id: metric for metric in candidates.filter(id__in=page).select_related("created_by", "owner")}
    hits = [
        MetricSearchHit(metric=metrics[metric_id], match_reason=lexical[metric_id].reason)
        for metric_id in page
        if metric_id in metrics
    ]
    confident = any(match.tier >= CONFIDENT_TIER for match in lexical.values())
    return MetricSearchResult(hits=hits, total=len(ranked), confident_match=confident, search_mode=SearchMode.LEXICAL)


def search_catalog(
    *,
    team: Team,
    user: User,
    user_access_control: "UserAccessControl",
    search: str,
    filters: MetricListFilters,
    limit: int = SEARCH_DEFAULT_LIMIT,
    offset: int = 0,
    analytics_props: AnalyticsProps | None = None,
) -> MetricSearchResult:
    """Search the metrics the list would show the user, and record the search without its text."""
    candidates = metrics_visible_to_user(team, user, user_access_control, filters)
    phrasings = split_search(search)
    result = search_metrics(candidates, phrasings, limit=limit, offset=offset)
    # Later pages of the same search are not new searches.
    if offset > 0:
        return result
    top = result.hits[0] if result.hits else None
    capture_metric_search_event(
        team=team,
        user=user,
        phrasing_count=len(phrasings),
        result_count=result.total,
        confident_match=result.confident_match,
        search_mode=result.search_mode,
        top_metric_name=top.metric.name if top else None,
        top_match_reason=top.match_reason if top else None,
        analytics_props=analytics_props,
    )
    return result
