"""What the answers say about one brand of the catalog: how often they name and cite it, which prompts and
searches lead to it, which sites they cite next to it, and how they speak about it.

The brand's answers come from its stored brand rows, as on the rankings. The project's own brands count as one
brand, and an own citation past the stored hosts still counts, through the check's cited flag.
"""

from __future__ import annotations

import uuid
import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from django.db import connection

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend import catalog
from products.aeo.backend.facade.contracts import (
    MAX_BRAND_PROMPTS,
    MAX_BRAND_SEARCHES,
    MAX_BRAND_SENTIMENT_EXAMPLES,
    MAX_BRAND_SITE_PAGES,
    MAX_BRAND_SITES,
    Brand,
    BrandCitedPage,
    BrandCitedSite,
    BrandDetail,
    BrandKind,
    BrandPrompt,
    BrandRates,
    BrandSearch,
    BrandSentiment,
    BrandSentimentExample,
    BrandStatus,
    CitedSiteRelation,
)
from products.aeo.backend.models import AEOBrand, AEOCheckBrand, AEOCitationCheck, AEOPrompt
from products.aeo.backend.page_urls import page_url_sql
from products.aeo.backend.rankings import MIN_PREVIOUS_ANSWERS_RATIO
from products.aeo.backend.scope import NAMED_SCOPE_SQL, CheckScope, named_scope_sql_params
from products.aeo.backend.sentiment import MAX_SENTENCE_CHARS, SENTIMENT_LABELS, mention_sentences, stored_mention_spans
from products.aeo.backend.window import CheckWindow

# One statement, so the brand's answers are found once for every list. `answered` reads the checks of both
# windows from their window index, and `brand_rows` the brand's rows from theirs, so the answer text and the
# wide check rows are never loaded. A brand has one row per answer, but the own brand stands for every own
# domain, so its rows are folded per answer first.
_BRAND_DETAIL_SQL = f"""
    WITH answered AS MATERIALIZED (
        SELECT check_row.id, check_row.prompt_id, check_row.engine, check_row.created_at,
            check_row.cited AS own_cited, check_row.target_best_position, check_row.brand_sentiment,
            check_row.created_at >= %(window_start)s AS current,
            (check_row.created_at AT TIME ZONE %(timezone)s)::date AS day
        FROM posthog_aeo_citation_check AS check_row
        WHERE check_row.team_id = %(team_id)s AND check_row.created_at >= %(since)s
            AND check_row.created_at < %(until)s AND check_row.check_failed = false
            AND check_row.mode = 'web_search'
            AND {NAMED_SCOPE_SQL}
    ),
    brand_rows AS MATERIALIZED (
        SELECT check_brand.citation_check_id AS id,
            bool_or(check_brand.mentioned OR check_brand.cited) AS visible,
            bool_or(check_brand.cited) AS cited,
            min(check_brand.citation_position) AS position,
            min(check_brand.sentiment) FILTER (WHERE check_brand.sentiment = ANY(%(labels)s)) AS sentiment
        FROM posthog_aeo_check_brand AS check_brand
        WHERE check_brand.team_id = %(team_id)s AND check_brand.created_at >= %(since)s
            AND check_brand.created_at < %(until)s AND check_brand.brand_id = ANY(%(brand_ids)s::uuid[])
        GROUP BY check_brand.citation_check_id
    ),
    hits AS MATERIALIZED (
        SELECT answered.id, answered.prompt_id, answered.engine, answered.created_at, answered.current, answered.day,
            coalesce(brand_rows.visible, false) OR (%(is_own)s AND answered.own_cited) AS visible,
            coalesce(brand_rows.cited, false) OR (%(is_own)s AND answered.own_cited) AS cited,
            CASE WHEN %(is_own)s THEN least(answered.target_best_position, brand_rows.position)
                ELSE brand_rows.position END AS position,
            -- The own brand's sentiment is scored on the check, a competitor's on its brand row.
            CASE WHEN %(is_own)s THEN
                CASE WHEN answered.brand_sentiment = ANY(%(labels)s) THEN answered.brand_sentiment END
                ELSE brand_rows.sentiment END AS sentiment
        FROM answered
        LEFT JOIN brand_rows ON brand_rows.id = answered.id
    ),
    named AS MATERIALIZED (
        SELECT id, prompt_id, engine FROM hits WHERE current AND visible
    ),
    top_sites AS MATERIALIZED (
        SELECT citation.domain, count(DISTINCT citation.citation_check_id) AS answers
        FROM posthog_aeo_check_citation AS citation
        JOIN named ON named.id = citation.citation_check_id
        WHERE citation.team_id = %(team_id)s AND citation.created_at >= %(window_start)s
            AND citation.created_at < %(until)s AND citation.domain <> ''
        GROUP BY citation.domain
        ORDER BY answers DESC, citation.domain
        LIMIT %(max_sites)s
    )
    SELECT
        (
            SELECT coalesce(json_agg(json_build_array(
                day, answers, visible, cited, position_sum, positioned, positive, neutral, negative
            ) ORDER BY day), '[]')
            FROM (
                SELECT day, count(*) AS answers,
                    count(*) FILTER (WHERE visible) AS visible,
                    count(*) FILTER (WHERE cited) AS cited,
                    coalesce(sum(position) FILTER (WHERE cited), 0) AS position_sum,
                    count(position) FILTER (WHERE cited) AS positioned,
                    count(*) FILTER (WHERE sentiment = 'positive') AS positive,
                    count(*) FILTER (WHERE sentiment = 'neutral') AS neutral,
                    count(*) FILTER (WHERE sentiment = 'negative') AS negative
                FROM hits GROUP BY day
            ) AS days
        ),
        (
            SELECT coalesce(json_agg(json_build_array(prompt_id, answers, visible, engines)
                ORDER BY visible DESC, prompt_id), '[]')
            FROM (
                SELECT prompt_id::text, count(*) AS answers, count(*) FILTER (WHERE visible) AS visible,
                    coalesce(array_agg(DISTINCT engine ORDER BY engine) FILTER (WHERE visible), '{{}}') AS engines
                FROM hits WHERE current
                GROUP BY prompt_id
                HAVING count(*) FILTER (WHERE visible) > 0
                ORDER BY count(*) FILTER (WHERE visible) DESC, prompt_id
                LIMIT %(max_prompts)s
            ) AS prompts
        ),
        (
            SELECT coalesce(json_agg(json_build_array(domain, page, answers) ORDER BY domain_answers DESC, domain,
                answers DESC, page), '[]')
            FROM (
                SELECT pages.*, top_sites.answers AS domain_answers,
                    row_number() OVER (PARTITION BY pages.domain ORDER BY pages.answers DESC, pages.page) AS place
                FROM top_sites
                JOIN (
                    SELECT citation.domain, {page_url_sql("citation.url")} AS page,
                        count(DISTINCT citation.citation_check_id) AS answers
                    FROM posthog_aeo_check_citation AS citation
                    JOIN named ON named.id = citation.citation_check_id
                    WHERE citation.team_id = %(team_id)s AND citation.created_at >= %(window_start)s
                        AND citation.created_at < %(until)s AND citation.domain <> '' AND citation.url <> ''
                    GROUP BY citation.domain, 2
                ) AS pages ON pages.domain = top_sites.domain
            ) AS ranked_pages
            WHERE place <= %(max_site_pages)s
        ),
        (
            SELECT coalesce(json_agg(json_build_array(domain, answers) ORDER BY answers DESC, domain), '[]')
            FROM top_sites
        ),
        (
            SELECT coalesce(json_agg(json_build_array(query, answers, prompts, engines)
                ORDER BY answers DESC, query), '[]')
            FROM (
                SELECT search.query, count(DISTINCT named.id) AS answers,
                    count(DISTINCT named.prompt_id) AS prompts,
                    array_agg(DISTINCT named.engine ORDER BY named.engine) AS engines
                FROM posthog_aeo_check_search AS search
                JOIN named ON named.id = search.citation_check_id
                WHERE search.team_id = %(team_id)s AND search.created_at >= %(window_start)s
                    AND search.created_at < %(until)s
                GROUP BY search.query
                ORDER BY answers DESC, search.query
                LIMIT %(max_searches)s
            ) AS searches
        ),
        (
            SELECT coalesce(json_agg(json_build_array(id, sentiment, engine, prompt_id)
                ORDER BY sentiment, place), '[]')
            FROM (
                SELECT id::text, sentiment, engine, prompt_id::text,
                    row_number() OVER (PARTITION BY sentiment ORDER BY created_at DESC, id) AS place
                FROM hits WHERE current AND sentiment IS NOT NULL
            ) AS examples
            WHERE place <= %(max_examples)s
        )
"""


@frozen
class _Day:
    answers: int
    mentioning: int
    cited: int
    position_sum: int
    positioned: int
    positive: int
    neutral: int
    negative: int

    @property
    def scored(self) -> int:
        return self.positive + self.neutral + self.negative


# The order of the counts in a day row of `_BRAND_DETAIL_SQL`.
_DAY_FIELDS = ("answers", "mentioning", "cited", "position_sum", "positioned", "positive", "neutral", "negative")


@frozen
class _BrandSubject:
    brand_ids: tuple[uuid.UUID, ...]
    domains: tuple[str, ...]
    is_own: bool


def subject_for(brand: AEOBrand) -> _BrandSubject:
    """The catalog brands a detail counts. An own brand counts with every other own brand, as on the rankings."""
    if not catalog.counts_as_own(brand.kind, brand.status):
        return _BrandSubject(brand_ids=(brand.id,), domains=(brand.domain,), is_own=False)
    own = list(
        AEOBrand.objects.for_team(brand.team_id)
        .filter(kind=BrandKind.OWN)
        .exclude(status=BrandStatus.IGNORED)
        .order_by("domain")
        .values_list("id", "domain")
    )
    return _BrandSubject(
        brand_ids=tuple(brand_id for brand_id, _ in own), domains=tuple(domain for _, domain in own), is_own=True
    )


def get_brand_detail(
    team_id: int, row: AEOBrand, *, brand: Brand, timezone_name: str, window: CheckWindow, scope: CheckScope
) -> BrandDetail:
    """`row` is the catalog brand, already read for the team, and `brand` its contract."""
    subject = subject_for(row)
    # The ORM reads map a child environment to its parent; raw SQL has to do the same.
    canonical_team_id = resolve_effective_team_id(team_id)
    with connection.cursor() as cursor:
        cursor.execute(
            _BRAND_DETAIL_SQL,
            {
                "team_id": canonical_team_id,
                "timezone": timezone_name,
                "since": window.previous_start,
                "window_start": window.start,
                "until": window.until,
                "brand_ids": list(subject.brand_ids),
                "is_own": subject.is_own,
                "labels": list(SENTIMENT_LABELS),
                "max_prompts": MAX_BRAND_PROMPTS,
                "max_sites": MAX_BRAND_SITES,
                "max_site_pages": MAX_BRAND_SITE_PAGES,
                "max_searches": MAX_BRAND_SEARCHES,
                "max_examples": MAX_BRAND_SENTIMENT_EXAMPLES,
                **named_scope_sql_params(scope),
            },
        )
        day_rows, prompt_rows, page_rows, site_rows, search_rows, example_rows = cursor.fetchone()

    days = {
        dt.date.fromisoformat(day): _Day(**dict(zip(_DAY_FIELDS, counts, strict=True))) for day, *counts in day_rows
    }
    current_days = {day: counts for day, counts in days.items() if day >= window.window_from}
    current = _sum(current_days.values())
    previous = _sum(counts for day, counts in days.items() if day < window.window_from)
    # As on the rankings, days before tracking started inside the previous window are too few to compare with.
    comparable = previous.answers > 0 and previous.answers >= current.answers * MIN_PREVIOUS_ANSWERS_RATIO
    answered_days = sorted(day for day, counts in current_days.items() if counts.answers)
    latest_date = answered_days[-1] if answered_days else None

    return BrandDetail(
        brand=brand,
        domains=subject.domains,
        window_from=window.window_from,
        window_to=window.window_to,
        days=window.days,
        branded=scope.segment,
        engine=scope.engine,
        topic=scope.topic,
        current=_rates(current),
        previous=_rates(previous) if comparable else None,
        latest_date=latest_date,
        latest=_rates(current_days[latest_date]) if latest_date else None,
        days_with_answers=len(answered_days),
        prompts=_prompts(team_id, prompt_rows),
        cited_sites=_cited_sites(team_id, subject, site_rows, page_rows, mentioning=current.mentioning),
        sentiment=BrandSentiment(
            scored=current.scored,
            positive_share=current.positive / current.scored if current.scored else None,
            neutral_share=current.neutral / current.scored if current.scored else None,
            negative_share=current.negative / current.scored if current.scored else None,
            examples=_examples(team_id, subject, example_rows),
        ),
        searches=tuple(
            BrandSearch(
                query=query,
                answers=answers,
                share_of_answers=answers / current.mentioning if current.mentioning else 0.0,
                prompts=prompts,
                engines=tuple(engines),
            )
            for query, answers, prompts, engines in search_rows
        ),
    )


def _sum(days: Iterable[_Day]) -> _Day:
    totals = dict.fromkeys(_DAY_FIELDS, 0)
    for day in days:
        for field in _DAY_FIELDS:
            totals[field] += getattr(day, field)
    return _Day(**totals)


def _rates(day: _Day) -> BrandRates:
    return BrandRates(
        answers=day.answers,
        answers_mentioning=day.mentioning,
        visibility=day.mentioning / day.answers if day.answers else None,
        citation_rate=day.cited / day.answers if day.answers else None,
        average_position=day.position_sum / day.positioned if day.positioned else None,
        positive_share=day.positive / day.scored if day.scored else None,
    )


def _prompts(team_id: int, rows: list[list[Any]]) -> tuple[BrandPrompt, ...]:
    prompts = {
        str(prompt_id): (text, topic)
        for prompt_id, text, topic in AEOPrompt.objects.for_team(team_id)
        .filter(id__in=[row[0] for row in rows])
        .values_list("id", "prompt", "topic")
    }
    return tuple(
        BrandPrompt(
            id=prompt_id,
            text=prompts[prompt_id][0],
            topic=prompts[prompt_id][1] or None,
            answers=answers,
            answers_mentioning=mentioning,
            mention_rate=mentioning / answers,
            engines=tuple(engines),
        )
        for prompt_id, answers, mentioning, engines in rows
        if prompt_id in prompts
    )


def _cited_sites(
    team_id: int,
    subject: _BrandSubject,
    site_rows: list[list[Any]],
    page_rows: list[list[Any]],
    *,
    mentioning: int,
) -> tuple[BrandCitedSite, ...]:
    """The brand's own domains are owned, and the other brands that compete in the answers, the project's own
    brands and its competitors, are competitors."""
    owned = set(subject.domains)
    competing = set(
        AEOBrand.objects.for_team(team_id)
        .filter(kind__in=[BrandKind.OWN, BrandKind.COMPETITOR])
        .exclude(status=BrandStatus.IGNORED)
        .values_list("domain", flat=True)
    )
    pages: defaultdict[str, list[BrandCitedPage]] = defaultdict(list)
    for domain, url, answers in page_rows:
        pages[domain].append(
            BrandCitedPage(url=url, answers=answers, share_of_answers=answers / mentioning if mentioning else 0.0)
        )
    return tuple(
        BrandCitedSite(
            domain=domain,
            answers=answers,
            share_of_answers=answers / mentioning if mentioning else 0.0,
            relation=CitedSiteRelation.OWNED
            if domain in owned
            else CitedSiteRelation.COMPETITOR
            if domain in competing
            else CitedSiteRelation.OTHER,
            pages=tuple(pages[domain]),
        )
        for domain, answers in site_rows
    )


def _examples(team_id: int, subject: _BrandSubject, rows: list[list[Any]]) -> tuple[BrandSentimentExample, ...]:
    """One sentence per example answer: for the own brand, a sentence the check scored with the answer's label,
    and for a competitor, the first sentence that holds a mention its row stored."""
    check_ids = [check_id for check_id, *_ in rows]
    checks = {
        str(check_id): (text or "", sentences or [])
        for check_id, text, sentences in AEOCitationCheck.objects.for_team(team_id)
        .filter(id__in=check_ids)
        .values_list("id", "answer_text", "brand_sentiment_sentences")
    }
    mentions: dict[str, list[dict[str, Any]]] = {}
    if not subject.is_own:
        mentions = {
            str(check_id): stored or []
            for check_id, stored in AEOCheckBrand.objects.for_team(team_id)
            .filter(citation_check_id__in=check_ids, brand_id__in=subject.brand_ids)
            .values_list("citation_check_id", "mentions")
        }
    examples: list[BrandSentimentExample] = []
    for check_id, label, engine, prompt_id in rows:
        text, scored_sentences = checks.get(check_id, ("", []))
        sentence = (
            _own_sentence(text, scored_sentences, label)
            if subject.is_own
            else _mention_sentence(text, mentions.get(check_id, []))
        )
        if sentence:
            examples.append(
                BrandSentimentExample(sentence=sentence, sentiment=label, engine=engine, prompt_id=prompt_id)
            )
    return tuple(examples)


def _own_sentence(text: str, scored: list[dict[str, Any]], label: str) -> str | None:
    for sentence in scored:
        start, end = sentence.get("start"), sentence.get("end")
        if sentence.get("label") == label and isinstance(start, int) and isinstance(end, int):
            return text[start:end].strip()[:MAX_SENTENCE_CHARS] or None
    return None


def _mention_sentence(text: str, mentions: list[dict[str, Any]]) -> str | None:
    sentences = mention_sentences(text, stored_mention_spans(text, mentions))
    return sentences[0].text if sentences else None
