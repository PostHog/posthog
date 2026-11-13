"""The project's keyword list, and how each keyword shows up in the prompts, the engines' searches and the answers.

A keyword matches as a case-insensitive phrase: a substring of the lowercased text. Modifiers are the words the
engines add to their searches beyond the prompt, which point at content the project does not have yet.
"""

from __future__ import annotations

import re
import json
import hashlib
import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

import tldextract

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.brand import brand_names, brand_regex
from products.aeo.backend.facade.contracts import (
    KEYWORD_MAX_LENGTH,
    MAX_KEYWORD_MODIFIERS,
    MAX_KEYWORDS_PER_TEAM,
    MAX_MODIFIER_EXAMPLES,
    BrandKind,
    Keyword,
    KeywordCreateResult,
    KeywordLimitError,
    KeywordModifier,
    KeywordModifierReport,
    KeywordNotFoundError,
    KeywordReport,
    KeywordReportRow,
    ModifierEngineCount,
    ModifierKind,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOKeyword


def normalize_keyword(text: str) -> str:
    return " ".join(text.split()).lower()


def list_keywords(team_id: int) -> list[Keyword]:
    return [_to_keyword(row) for row in AEOKeyword.objects.for_team(team_id).order_by("keyword")]


def get_keyword(team_id: int, keyword_id: str) -> Keyword:
    return _to_keyword(_get_keyword_row(team_id, keyword_id))


def create_keywords(team_id: int, texts: Iterable[str]) -> KeywordCreateResult:
    """Add keywords to the list. Blank entries, entries longer than the column, and keywords the list
    already has are skipped. Raises KeywordLimitError when the new ones would pass the cap."""
    # bulk_create skips RootTeamMixin.save(), so a child environment's id has to become its parent's here or
    # the rows land under an id that for_team() never reads.
    team_id = resolve_effective_team_id(team_id)
    texts = list(texts)
    wanted = list(
        dict.fromkeys(keyword for text in texts if 0 < len(keyword := normalize_keyword(text)) <= KEYWORD_MAX_LENGTH)
    )
    with transaction.atomic():
        # Serializes creates per team, so two concurrent requests can't each pass the cap check.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('aeo_keyword'), %s::int)", [team_id])
        existing = set(AEOKeyword.objects.for_team(team_id).values_list("keyword", flat=True))
        new = [keyword for keyword in wanted if keyword not in existing]
        if len(existing) + len(new) > MAX_KEYWORDS_PER_TEAM:
            raise KeywordLimitError(
                f"A project can track up to {MAX_KEYWORDS_PER_TEAM} keywords. It has {len(existing)}, and this "
                f"request adds {len(new)}. Remove some keywords first."
            )
        AEOKeyword.objects.for_team(team_id).bulk_create(
            [AEOKeyword(team_id=team_id, keyword=keyword) for keyword in new]
        )
    return KeywordCreateResult(created=len(new), skipped=len(texts) - len(new))


def delete_keyword(team_id: int, keyword_id: str) -> None:
    _get_keyword_row(team_id, keyword_id).delete()


def _get_keyword_row(team_id: int, keyword_id: str) -> AEOKeyword:
    try:
        return AEOKeyword.objects.for_team(team_id).get(id=keyword_id)
    except (AEOKeyword.DoesNotExist, ValueError, ValidationError) as error:
        raise KeywordNotFoundError(keyword_id) from error


def _to_keyword(row: AEOKeyword) -> Keyword:
    return Keyword(id=str(row.id), keyword=row.keyword, created_at=row.created_at)


@frozen
class _Window:
    window_from: dt.date
    window_to: dt.date
    start: dt.datetime
    until: dt.datetime


def _window(timezone_name: str, days: int) -> _Window:
    tz = ZoneInfo(timezone_name)
    until = timezone.now()
    window_to = until.astimezone(tz).date()
    window_from = window_to - dt.timedelta(days=days - 1)
    return _Window(
        window_from=window_from,
        window_to=window_to,
        start=dt.datetime.combine(window_from, dt.time.min, tzinfo=tz),
        until=until,
    )


# `answered` lowercases each answered check once, so the keyword cross join only runs strpos. A check's
# searches are joined with newlines, which a keyword can't contain, so no match spans two searches. A null
# brand pattern (no target domain) leaves `mentioned` to the citation alone and `mention_depth` null.
# `matched` keeps only the pairs where the keyword occurs, since every aggregate below filters on a match.
# It is MATERIALIZED because Postgres otherwise inlines it and evaluates the `uses` replace() once for each
# aggregate that reads it.
_KEYWORD_REPORT_SQL = """
    WITH answered AS MATERIALIZED (
        SELECT check_row.prompt_id, check_row.cited, check_row.target_best_position,
            lower(check_row.prompt_text) AS prompt_text,
            lower(coalesce(check_row.answer_text, '')) AS answer_text,
            lower(array_to_string(ARRAY(
                SELECT jsonb_array_elements_text(
                    CASE WHEN jsonb_typeof(check_row.search_queries) = 'array' THEN check_row.search_queries ELSE '[]'::jsonb END
                )
            ), E'\\n')) AS searches,
            check_row.cited OR coalesce(check_row.answer_text ~* %(brand)s::text, false) AS mentioned,
            CASE WHEN length(check_row.answer_text) > 0
                THEN (regexp_instr(check_row.answer_text, %(brand)s::text, 1, 1, 0, 'i') - 1)::float / length(check_row.answer_text)
            END AS mention_depth
        FROM posthog_aeo_citation_check AS check_row
        WHERE check_row.team_id = %(team_id)s AND check_row.created_at >= %(since)s
            AND check_row.created_at < %(until)s AND check_row.check_failed = false
    ),
    matched AS MATERIALIZED (
        SELECT keyword, answered.prompt_id, answered.cited, answered.mentioned, answered.target_best_position,
            answered.mention_depth,
            strpos(answered.prompt_text, keyword) > 0 AS in_prompt,
            strpos(answered.searches, keyword) > 0 AS in_searches,
            CASE WHEN strpos(answered.answer_text, keyword) > 0
                THEN (length(answered.answer_text) - length(replace(answered.answer_text, keyword, ''))) / length(keyword)
                ELSE 0
            END AS uses
        FROM answered CROSS JOIN unnest(%(keywords)s::text[]) AS keyword
        WHERE strpos(answered.prompt_text, keyword) > 0 OR strpos(answered.searches, keyword) > 0
            OR strpos(answered.answer_text, keyword) > 0
    )
    SELECT keyword,
        count(DISTINCT prompt_id) FILTER (WHERE in_prompt),
        count(*) FILTER (WHERE in_prompt),
        count(*) FILTER (WHERE in_prompt AND mentioned),
        count(*) FILTER (WHERE in_prompt AND cited),
        count(*) FILTER (WHERE in_searches),
        count(*) FILTER (WHERE in_searches AND cited),
        count(*) FILTER (WHERE uses > 0),
        coalesce(sum(uses) FILTER (WHERE uses > 0), 0),
        count(*) FILTER (WHERE uses > 0 AND mentioned),
        avg(target_best_position) FILTER (WHERE uses > 0 AND cited),
        percentile_cont(0.5) WITHIN GROUP (ORDER BY mention_depth) FILTER (WHERE uses > 0 AND mention_depth >= 0)
    FROM matched
    GROUP BY keyword
"""


# Checks run at most a few times a day, so a report a few minutes old loses nothing, and the scan over a
# month of answers stays off most page views.
KEYWORD_REPORT_CACHE_SECONDS = 10 * 60


def get_keyword_report(team_id: int, *, target_domains: list[str], timezone_name: str, days: int) -> KeywordReport:
    window = _window(timezone_name, days)
    keywords = list(AEOKeyword.objects.for_team(team_id).order_by("keyword").values_list("keyword", flat=True))
    # The key carries the keyword list and the window's last day, so adding or removing a keyword, or a new day,
    # misses the cache instead of serving a stale report.
    fingerprint = hashlib.sha256(json.dumps([sorted(target_domains), keywords]).encode()).hexdigest()
    cache_key = f"aeo_keyword_report:{team_id}:{days}:{timezone_name}:{window.window_to.isoformat()}:{fingerprint}"
    cached = cache.get(cache_key)
    if isinstance(cached, KeywordReport):
        return cached
    report = _build_keyword_report(team_id, window, keywords, target_domains=target_domains, days=days)
    cache.set(cache_key, report, KEYWORD_REPORT_CACHE_SECONDS)
    return report


def _build_keyword_report(
    team_id: int, window: _Window, keywords: list[str], *, target_domains: list[str], days: int
) -> KeywordReport:
    answers = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(created_at__gte=window.start, created_at__lt=window.until, check_failed=False)
        .count()
    )
    rows: dict[str, tuple[Any, ...]] = {}
    if keywords and answers:
        with connection.cursor() as cursor:
            cursor.execute(
                _KEYWORD_REPORT_SQL,
                {
                    # The ORM reads map a child environment to its parent; raw SQL has to do the same.
                    "team_id": resolve_effective_team_id(team_id),
                    "since": window.start,
                    "until": window.until,
                    "brand": brand_regex(target_domains),
                    "keywords": keywords,
                },
            )
            rows = {row[0]: row[1:] for row in cursor.fetchall()}
    return KeywordReport(
        days=days,
        window_from=window.window_from,
        window_to=window.window_to,
        answers=answers,
        brand_names=brand_names(target_domains),
        keywords=tuple(_report_row(keyword, rows.get(keyword), answers) for keyword in keywords),
    )


def _rate(part: float, whole: int) -> float | None:
    return part / whole if whole else None


def _report_row(keyword: str, row: tuple[Any, ...] | None, answers: int) -> KeywordReportRow:
    (
        prompts,
        prompt_checks,
        prompt_mentioned,
        prompt_cited,
        searched,
        searched_cited,
        in_answer,
        uses,
        answer_mentioned,
        avg_position,
        median_depth,
    ) = row or (0, 0, 0, 0, 0, 0, 0, 0, 0, None, None)
    return KeywordReportRow(
        keyword=keyword,
        prompts=prompts,
        prompt_checks=prompt_checks,
        prompt_mention_rate=_rate(prompt_mentioned, prompt_checks),
        prompt_cited_rate=_rate(prompt_cited, prompt_checks),
        searched_checks=searched,
        searched_rate=_rate(searched, answers),
        searched_cited_rate=_rate(searched_cited, searched),
        answer_checks=in_answer,
        answer_rate=_rate(in_answer, answers),
        uses_per_answer=_rate(float(uses), in_answer),
        answer_mention_rate=_rate(answer_mentioned, in_answer),
        avg_citation_position=float(avg_position) if avg_position is not None else None,
        median_first_mention_depth=median_depth,
    )


# Function words a search adds for grammar, not meaning. Comparison words such as "vs" and "best" are
# modifiers, so they are not here.
STOPWORDS = frozenset(
    """a about after an and any are as at be been but by can could do does for from get has have how i if in into
    is it its me my of on or our should so than that the their them then there these this those to us was we what
    when where which who why will with without would you your""".split()
)
# Parts of a domain that only show when a search writes a domain loosely, as in "example com".
TLD_PARTS = frozenset("com io org net co uk www http https".split())
PHRASE_ABSORPTION = 0.8

FRESHNESS_TERMS = frozenset({"latest", "new", "updated"})
PRICING_TERMS = frozenset({"price", "pricing", "cost", "costs", "plan", "plans", "free", "cheap", "per"})
COMPARISON_TERMS = frozenset(
    {"vs", "versus", "alternative", "alternatives", "comparison", "compare", "competitors", "best", "top"}
)
DOCS_TERMS = frozenset({"docs", "documentation", "official", "sdk", "api", "guide", "tutorial", "github"})
_YEAR = re.compile(r"^(199\d|20\d\d)$")
# A token keeps inner dots and hyphens and a leading "site:", so "self-hosted", "example.com" and
# "site:example.com" stay whole. Everything else splits.
_TOKEN = re.compile(r"(?:site:)?[^\W_](?:[\w.\-]*[^\W_])?", re.UNICODE)

_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _is_word(token: str) -> bool:
    return len(token) > 1 and token not in STOPWORDS and token not in TLD_PARTS


def _prompt_vocabulary(prompt_text: str) -> set[str]:
    # A prompt that says "self-hosted" also covers a search for "self hosted".
    tokens = tokenize(prompt_text)
    return {*tokens, *(part for token in tokens for part in re.split(r"[.\-]", token) if part)}


def check_modifiers(prompt_text: str, searches: Iterable[str]) -> dict[str, str]:
    """The modifiers of one check, each with the first search that used it. A phrase counts only when both
    of its words are new, so a prompt word next to a new word ("analytics 2026") does not hide the new word."""
    vocabulary = _prompt_vocabulary(prompt_text)
    found: dict[str, str] = {}
    for search in searches:
        tokens = tokenize(search)
        for token in tokens:
            if _is_word(token) and token not in vocabulary:
                found.setdefault(token, search)
        for phrase in _phrases(tokens):
            if phrase.first not in vocabulary and phrase.second not in vocabulary:
                found.setdefault(f"{phrase.first} {phrase.second}", search)
    return found


@frozen
class _Phrase:
    first: str
    second: str


def _phrases(tokens: list[str]) -> list[_Phrase]:
    return [
        _Phrase(first=first, second=second)
        for first, second in zip(tokens, tokens[1:])
        if _is_word(first) and _is_word(second)
    ]


def modifier_kind(term: str, competitor_names: frozenset[str]) -> ModifierKind:
    if term.startswith("site:"):
        return ModifierKind.SITE
    if term in competitor_names:
        return ModifierKind.COMPETITOR
    words = term.split()
    for kind, matches in (
        (ModifierKind.FRESHNESS, lambda word: bool(_YEAR.match(word)) or word in FRESHNESS_TERMS),
        (ModifierKind.PRICING, PRICING_TERMS.__contains__),
        (ModifierKind.COMPARISON, COMPARISON_TERMS.__contains__),
        (ModifierKind.DOCS, DOCS_TERMS.__contains__),
    ):
        if any(matches(word) for word in words):
            return kind
    return ModifierKind.OTHER


def competitor_names(team_id: int) -> frozenset[str]:
    names: set[str] = set()
    for name, domain, aliases in (
        AEOBrand.objects.for_team(team_id).filter(kind=BrandKind.COMPETITOR).values_list("name", "domain", "aliases")
    ):
        names.add(normalize_keyword(name))
        names.add(domain.lower())
        if label := _DOMAIN_PARTS(domain).domain:
            names.add(label.lower())
        if isinstance(aliases, list):
            names.update(normalize_keyword(str(alias)) for alias in aliases)
    names.discard("")
    return frozenset(names)


# Bounds the distinct terms held in memory while counting, which the window and chunked reads do not. Diverse
# searches give most terms a single answer, and those rarely reach the top MAX_KEYWORD_MODIFIERS.
MAX_TRACKED_MODIFIER_TERMS = 20_000
MODIFIER_PAGE_SIZE = 2000


class _ModifierCounts:
    """Modifier counts across checks. Each modifier counts once per check, so every number reads as answers.

    Past `max_terms` distinct terms, only the most used half is kept. A dropped term that comes back counts
    again from zero, so a term that was rare early in the window can read low."""

    def __init__(self, max_terms: int = MAX_TRACKED_MODIFIER_TERMS) -> None:
        self.answers = 0
        self.cited = 0
        self._max_terms = max_terms
        self._checks: Counter[str] = Counter()
        self._cited: Counter[str] = Counter()
        self._engines: Counter[tuple[str, str]] = Counter()
        self._examples: defaultdict[str, dict[str, None]] = defaultdict(dict)

    def add(self, *, engine: str, cited: bool, modifiers: dict[str, str]) -> None:
        # Each search comes in with its whitespace already collapsed, so the examples hold references to the
        # check's search strings instead of a new copy per term.
        self.answers += 1
        self.cited += cited
        for term, search in modifiers.items():
            self._checks[term] += 1
            self._cited[term] += cited
            self._engines[term, engine] += 1
            examples = self._examples[term]
            if len(examples) < MAX_MODIFIER_EXAMPLES:
                examples[search] = None
        if len(self._checks) > self._max_terms:
            self._drop_least_used()

    def _drop_least_used(self) -> None:
        kept = {term for term, _ in self._checks.most_common(self._max_terms // 2)}
        self._checks = Counter({term: count for term, count in self._checks.items() if term in kept})
        self._cited = Counter({term: count for term, count in self._cited.items() if term in kept})
        self._engines = Counter({key: count for key, count in self._engines.items() if key[0] in kept})
        self._examples = defaultdict(dict, {term: ex for term, ex in self._examples.items() if term in kept})

    def ranked(self, competitors: frozenset[str]) -> tuple[KeywordModifier, ...]:
        absorbed = self._absorbed_words()
        terms = sorted((term for term in self._checks if term not in absorbed), key=lambda t: (-self._checks[t], t))
        terms = terms[:MAX_KEYWORD_MODIFIERS]
        engines: defaultdict[str, list[tuple[str, int]]] = defaultdict(list)
        shown = set(terms)
        for (term, engine), count in self._engines.items():
            if term in shown:
                engines[term].append((engine, count))
        return tuple(
            KeywordModifier(
                term=term,
                kind=modifier_kind(term, competitors),
                answers=self._checks[term],
                share=self._checks[term] / self.answers,
                cited_rate=self._cited[term] / self._checks[term],
                engines=tuple(
                    ModifierEngineCount(engine=engine, answers=count)
                    for engine, count in sorted(engines[term], key=lambda item: (-item[1], item[0]))
                ),
                example_searches=tuple(self._examples[term]),
            )
            for term in terms
        )

    def _absorbed_words(self) -> set[str]:
        # A word that nearly always appears inside one phrase ("hosted" in "self hosted") reads better as the phrase.
        absorbed: set[str] = set()
        for term, count in self._checks.items():
            if " " not in term:
                continue
            for word in term.split():
                if word in self._checks and count >= PHRASE_ABSORPTION * self._checks[word]:
                    absorbed.add(word)
        return absorbed


def get_keyword_modifiers(
    team_id: int, *, timezone_name: str, days: int, keyword: str | None = None
) -> KeywordModifierReport:
    window = _window(timezone_name, days)
    keyword = normalize_keyword(keyword) if keyword else None
    counts = _ModifierCounts()
    checks = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(created_at__gte=window.start, created_at__lt=window.until, check_failed=False)
        .order_by("id")
    )
    # Keyset pages, because PgBouncer turns server-side cursors off and `.iterator()` would then load the whole window.
    last_id = None
    while True:
        page = list(
            (checks.filter(id__gt=last_id) if last_id else checks).values_list(
                "id", "engine", "cited", "prompt_text", "search_queries"
            )[:MODIFIER_PAGE_SIZE]
        )
        for _, engine, cited, prompt_text, search_queries in page:
            searches = (
                [" ".join(str(search).split()) for search in search_queries] if isinstance(search_queries, list) else []
            )
            if keyword and not any(keyword in search.lower() for search in searches):
                continue
            counts.add(engine=engine, cited=cited, modifiers=check_modifiers(prompt_text, searches))
        if len(page) < MODIFIER_PAGE_SIZE:
            break
        last_id = page[-1][0]
    return KeywordModifierReport(
        days=days,
        window_from=window.window_from,
        window_to=window.window_to,
        keyword=keyword,
        answers=counts.answers,
        baseline_cited_rate=_rate(counts.cited, counts.answers),
        modifiers=counts.ranked(competitor_names(team_id)) if counts.answers else (),
    )
