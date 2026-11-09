"""Brand visibility against competitors, and the domains and pages the engines cite.

Competitors are not configured anywhere: they are the brands behind the domains the engines cite
most, minus the review sites, forums and social networks that answers cite for every brand.
"""

from __future__ import annotations

import re
import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

import tldextract

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.brand import brand_names, brand_regex
from products.aeo.backend.facade.contracts import (
    MAX_RANKED_COMPETITORS,
    MAX_RANKED_DOMAINS,
    MAX_RANKED_PAGES,
    PromptSetRankings,
    RankedBrand,
    RankedBrandDay,
    RankedDomain,
    RankedPage,
)
from products.aeo.backend.models import AEOCitationCheck

# Registrable names of sites answers cite whatever the brand, so they are never a competitor.
NON_BRAND_NAMES = frozenset(
    """capterra dev facebook g2 gartner github instagram linkedin medium producthunt quora reddit
    stackexchange stackoverflow substack trustradius twitter wikipedia x ycombinator youtube""".split()
)

_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())

# One row per brand and day: answered checks that day, and how many of them named the brand. An
# answer names a brand when its text has the brand's name as a word, or it cites a host on the brand's
# registrable domain; for the project's own brand any cited answer also counts, as in the mention rate.
_BRAND_DAYS_SQL = """
    SELECT brand.domain, (check_row.created_at AT TIME ZONE %s)::date AS day, count(*),
        count(*) FILTER (
            WHERE check_row.answer_text ~* brand.pattern
                OR (brand.is_target AND check_row.cited)
                OR (
                    jsonb_typeof(check_row.top_cited_domains) = 'array'
                    AND EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(check_row.top_cited_domains) AS host
                        WHERE host = brand.domain OR right(host, length(brand.domain) + 1) = '.' || brand.domain
                    )
                )
        )
    FROM posthog_aeo_citation_check AS check_row
    CROSS JOIN unnest(%s::text[], %s::text[], %s::bool[]) AS brand(domain, pattern, is_target)
    WHERE check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s AND check_row.check_failed = false
    GROUP BY brand.domain, day
"""

# A JSON field that is not a list reads as an empty one, so one malformed row can't fail the query.
_CITED_HOSTS_SQL = """
    SELECT DISTINCT lower(host)
    FROM posthog_aeo_citation_check AS check_row,
        jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(check_row.top_cited_domains) = 'array' THEN check_row.top_cited_domains ELSE '[]'::jsonb END
        ) AS host
    WHERE check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s AND check_row.check_failed = false
"""
# The host to registrable domain mapping arrives as two parallel arrays.
_DOMAIN_ANSWERS_SQL = """
    SELECT mapping.domain, count(DISTINCT check_row.id)
    FROM unnest(%s::text[], %s::text[]) AS mapping(host, domain),
        posthog_aeo_citation_check AS check_row,
        jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(check_row.top_cited_domains) = 'array' THEN check_row.top_cited_domains ELSE '[]'::jsonb END
        ) AS cited_host
    WHERE lower(cited_host) = mapping.host
        AND check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s AND check_row.check_failed = false
    GROUP BY mapping.domain
"""
# URLs per host never overlap, so a domain's distinct URLs are the sum over its hosts.
_DOMAIN_URLS_SQL = """
    SELECT mapping.domain, count(DISTINCT url)
    FROM unnest(%s::text[], %s::text[]) AS mapping(host, domain),
        posthog_aeo_citation_check AS check_row,
        jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(check_row.cited_urls) = 'array' THEN check_row.cited_urls ELSE '[]'::jsonb END
        ) AS url
    WHERE lower(substring(url from '^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/?#]*@)?([^/:?#]+)')) = mapping.host
        AND check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s AND check_row.check_failed = false
    GROUP BY mapping.domain
"""
_PAGES_SQL = """
    SELECT url, count(DISTINCT check_row.id)
    FROM posthog_aeo_citation_check AS check_row,
        jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(check_row.cited_urls) = 'array' THEN check_row.cited_urls ELSE '[]'::jsonb END
        ) AS url
    WHERE url <> '' AND check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s AND check_row.check_failed = false
    GROUP BY url
    ORDER BY count(DISTINCT check_row.id) DESC, url
    LIMIT %s
"""


@lru_cache(maxsize=4096)
def registrable_domain(host: str) -> str:
    parts = _DOMAIN_PARTS(host)
    return parts.top_domain_under_public_suffix or host


def get_rankings(team_id: int, *, target_domains: list[str], timezone_name: str, days: int) -> PromptSetRankings:
    tz = ZoneInfo(timezone_name)
    window_to = timezone.now().astimezone(tz).date()
    window_from = window_to - dt.timedelta(days=days - 1)
    window_start = dt.datetime.combine(window_from, dt.time.min, tzinfo=tz)
    previous_start = window_start - dt.timedelta(days=days)

    # Every read stops at the same instant, so a check written mid-request can't make the counts disagree.
    until = timezone.now()
    answered = AEOCitationCheck.objects.for_team(team_id).filter(
        created_at__gte=window_start, created_at__lt=until, check_failed=False
    )
    answers = answered.count()

    # A target like docs.example.com stands for the whole example.com brand.
    targets = {registrable_domain(domain.lower()) for domain in target_domains}
    citations = _Citations(resolve_effective_team_id(team_id), since=window_start, until=until)
    ranked_domains = citations.ranked_domains()
    competitors = _competitors(ranked_domains, targets, brand_names(target_domains))
    top_domains = ranked_domains[:MAX_RANKED_DOMAINS]
    domain_urls = citations.urls_per_domain([domain for domain, _ in top_domains])
    target_domain = registrable_domain(target_domains[0].lower()) if target_domains else None
    brands = ([(target_domain, brand_regex(target_domains), True)] if target_domain else []) + [
        (domain, rf"\m{re.escape(_brand_name(domain))}\M", False) for domain in competitors
    ]
    brand_days = _brand_days(
        team_id,
        brands=[brand for brand in brands if brand[1]],
        timezone_name=timezone_name,
        since=previous_start,
        until=until,
        window_from=window_from,
    )
    positive_share = _positive_share(answered) if target_domain else None

    ranked_brands = sorted(
        (
            RankedBrand(
                domain=domain,
                name=", ".join(brand_names(target_domains)) if is_target else _brand_name(domain),
                is_target=is_target,
                answers_mentioning=brand_days.current[domain][1],
                visibility=_share(*brand_days.current[domain]),
                previous_visibility=_share(*brand_days.previous[domain]),
                positive_share=positive_share if is_target else None,
            )
            for domain, _, is_target in brands
        ),
        key=lambda brand: (-(brand.visibility or 0), brand.domain),
    )
    return PromptSetRankings(
        days=days,
        window_from=window_from,
        window_to=window_to,
        answers=answers,
        brands=tuple(ranked_brands),
        daily=brand_days.daily,
        top_domains=tuple(
            RankedDomain(
                domain=domain,
                answers=count,
                share_of_answers=count / answers if answers else 0.0,
                urls=domain_urls.get(domain, 0),
                is_target=domain in targets,
                is_competitor=domain in competitors,
            )
            for domain, count in top_domains
        ),
        top_pages=tuple(
            RankedPage(
                url=page.url,
                answers=page.answers,
                share_of_answers=page.answers / answers if answers else 0.0,
                is_target=page.domain in targets,
            )
            for page in citations.top_pages()
        ),
    )


@frozen
class _CitedPage:
    url: str
    domain: str
    answers: int


@frozen
class _BrandDays:
    """Answers and mentions per brand, as [answers, mentioning], in each window, and the current window per day."""

    current: defaultdict[str, list[int]]
    previous: defaultdict[str, list[int]]
    daily: tuple[RankedBrandDay, ...]


class _Citations:
    """Cited registrable domains and pages across the answered checks in a window, counted in Postgres
    once per answer. Python only maps the distinct cited hosts to registrable domains, which needs the
    public suffix list."""

    def __init__(self, team_id: int, *, since: dt.datetime, until: dt.datetime) -> None:
        self._params: list[Any] = [team_id, since, until]
        with connection.cursor() as cursor:
            cursor.execute(_CITED_HOSTS_SQL, self._params)
            hosts = [host for (host,) in cursor.fetchall() if host]
        self._host_domains = {host: registrable_domain(host) for host in hosts}

    def ranked_domains(self) -> list[tuple[str, int]]:
        """Every cited registrable domain with the answers that cited it, most cited first."""
        if not self._host_domains:
            return []
        with connection.cursor() as cursor:
            cursor.execute(_DOMAIN_ANSWERS_SQL, [*self._mapping(self._host_domains), *self._params])
            return _ranked(dict(cursor.fetchall()), len(self._host_domains))

    def urls_per_domain(self, domains: list[str]) -> dict[str, int]:
        mapping = {host: domain for host, domain in self._host_domains.items() if domain in set(domains)}
        if not mapping:
            return {}
        with connection.cursor() as cursor:
            cursor.execute(_DOMAIN_URLS_SQL, [*self._mapping(mapping), *self._params])
            return dict(cursor.fetchall())

    def top_pages(self) -> list[_CitedPage]:
        """The most cited pages. URLs that don't parse are skipped, so the query reads a few extra rows
        to fill the list."""
        with connection.cursor() as cursor:
            cursor.execute(_PAGES_SQL, [*self._params, MAX_RANKED_PAGES * 2])
            rows = cursor.fetchall()
        pages: list[_CitedPage] = []
        for url, count in rows:
            try:
                host = (urlparse(url).hostname or "").lower()
            except ValueError:
                continue
            if host and len(pages) < MAX_RANKED_PAGES:
                pages.append(_CitedPage(url=url, domain=registrable_domain(host), answers=count))
        return pages

    @staticmethod
    def _mapping(host_domains: dict[str, str]) -> list[list[str]]:
        return [list(host_domains.keys()), list(host_domains.values())]


def _competitors(ranked_domains: list[tuple[str, int]], targets: set[str], target_names: tuple[str, ...]) -> list[str]:
    # The project's own brand on another domain (example.de for example.com) is not a competitor.
    excluded = NON_BRAND_NAMES | set(target_names)
    competitors: list[str] = []
    for domain, _ in ranked_domains:
        if len(competitors) == MAX_RANKED_COMPETITORS:
            break
        if domain not in targets and _brand_name(domain) not in excluded:
            competitors.append(domain)
    return competitors


def _brand_days(
    team_id: int,
    *,
    brands: list[tuple[str, str | None, bool]],
    timezone_name: str,
    since: dt.datetime,
    until: dt.datetime,
    window_from: dt.date,
) -> _BrandDays:
    current: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    previous: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    if not brands:
        return _BrandDays(current=current, previous=previous, daily=())
    # The ORM reads above map a child environment to its parent; raw SQL has to do the same.
    effective_team_id = resolve_effective_team_id(team_id)
    with connection.cursor() as cursor:
        cursor.execute(
            _BRAND_DAYS_SQL,
            [
                timezone_name,
                [domain for domain, _, _ in brands],
                [pattern for _, pattern, _ in brands],
                [is_target for _, _, is_target in brands],
                effective_team_id,
                since,
                until,
            ],
        )
        rows = cursor.fetchall()
    daily: list[RankedBrandDay] = []
    for domain, day, answers, mentioning in rows:
        totals = current if day >= window_from else previous
        totals[domain][0] += answers
        totals[domain][1] += mentioning
        if day >= window_from:
            daily.append(
                RankedBrandDay(date=day, domain=domain, answers=answers, visibility=_share(answers, mentioning))
            )
    return _BrandDays(
        current=current, previous=previous, daily=tuple(sorted(daily, key=lambda row: (row.date, row.domain)))
    )


def _positive_share(answered: QuerySet[AEOCitationCheck]) -> float | None:
    counts = answered.aggregate(
        scored=Count("id", filter=Q(brand_sentiment__isnull=False)),
        positive=Count("id", filter=Q(brand_sentiment="positive")),
    )
    return counts["positive"] / counts["scored"] if counts["scored"] else None


def _brand_name(domain: str) -> str:
    return (_DOMAIN_PARTS(domain).domain or domain).lower()


def _share(answers: int, mentioning: int) -> float | None:
    return mentioning / answers if answers else None


def _ranked(counter: Mapping[str, int], limit: int) -> list[tuple[str, int]]:
    # Ties break on the value, so the order is stable between two requests.
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
