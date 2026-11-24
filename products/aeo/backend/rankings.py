"""Brand visibility against competitors, and the domains and pages the engines cite.

Competitors are not configured anywhere: they are the brands behind the domains the engines cite
most, minus the review sites, forums and social networks that answers cite for every brand.
"""

from __future__ import annotations

import uuid
import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from django.db import connection
from django.db.models import Count, Q, QuerySet

import tldextract

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.brand import brand_names
from products.aeo.backend.facade.contracts import (
    MAX_RANKED_COMPETITORS,
    MAX_RANKED_DOMAINS,
    MAX_RANKED_PAGES,
    BrandKind,
    BrandStatus,
    CheckMode,
    PromptSetRankings,
    RankedBrand,
    RankedBrandDay,
    RankedDomain,
    RankedPage,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck
from products.aeo.backend.scope import (
    NAMED_SCOPE_SQL,
    SCOPE_SQL,
    CheckScope,
    named_scope_sql_params,
    scope_filter,
    scope_sql_params,
)
from products.aeo.backend.window import CheckWindow

# Registrable names of sites answers cite whatever the brand, so they are never a competitor.
NON_BRAND_NAMES = frozenset(
    """capterra dev facebook g2 gartner github instagram linkedin medium producthunt quora reddit
    stackexchange stackoverflow substack trustradius twitter wikipedia x ycombinator youtube""".split()
)

_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())

# One row per ranked brand and day: answered checks that day, and how many of them named or cited the brand,
# from the stored brand rows. A ranked brand stands for one or more catalog brands: the project's own brands
# rank together as the target. Both tables are narrowed by team and time, so the answer text and the wide
# check rows are never loaded.
_BRAND_DAYS_SQL = f"""
    WITH answered AS MATERIALIZED (
        SELECT check_row.id, check_row.cited, (check_row.created_at AT TIME ZONE %(timezone)s)::date AS day
        FROM posthog_aeo_citation_check AS check_row
        WHERE check_row.team_id = %(team_id)s AND check_row.created_at >= %(since)s
            AND check_row.created_at < %(until)s AND check_row.check_failed = false
            AND check_row.mode = 'web_search'
            AND {NAMED_SCOPE_SQL}
    ),
    days AS (
        SELECT day, count(*) AS answers FROM answered GROUP BY day
    ),
    mentioning AS (
        SELECT mention.domain, answered.day, count(DISTINCT answered.id) AS answers
        FROM (
            SELECT ranked.domain, check_brand.citation_check_id AS id
            FROM posthog_aeo_check_brand AS check_brand
            JOIN unnest(%(brand_ids)s::uuid[], %(brand_domains)s::text[]) AS ranked(brand_id, domain)
                ON ranked.brand_id = check_brand.brand_id
            WHERE check_brand.team_id = %(team_id)s AND check_brand.created_at >= %(since)s
                AND check_brand.created_at < %(until)s AND (check_brand.mentioned OR check_brand.cited)
            UNION ALL
            -- The check keeps only its first cited hosts, but its cited flag saw them all, so it also
            -- counts the target for a citation past the stored hosts.
            SELECT %(target_domain)s::text, answered.id FROM answered
            WHERE answered.cited AND %(target_domain)s::text IS NOT NULL
        ) AS mention
        JOIN answered ON answered.id = mention.id
        GROUP BY mention.domain, answered.day
    )
    SELECT ranked.domain, days.day, days.answers, coalesce(mentioning.answers, 0)
    FROM days
    CROSS JOIN unnest(%(domains)s::text[]) AS ranked(domain)
    LEFT JOIN mentioning ON mentioning.domain = ranked.domain AND mentioning.day = days.day
"""

# The cited URL rows of the answered checks in a window and scope. Both tables are narrowed by team and
# time, so each side is read from its own window index and the wide check rows are never loaded.
_CITED_FROM_SQL = f"""
    FROM posthog_aeo_check_citation AS citation
    JOIN posthog_aeo_citation_check AS check_row ON check_row.id = citation.citation_check_id
    WHERE citation.team_id = %s AND citation.created_at >= %s AND citation.created_at < %s
        AND check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s
        AND check_row.check_failed = false AND check_row.mode = 'web_search'
        AND {SCOPE_SQL}
"""
_DOMAIN_ANSWERS_SQL = f"""
    SELECT citation.domain, count(DISTINCT citation.citation_check_id)
    {_CITED_FROM_SQL}
        AND citation.domain <> ''
    GROUP BY citation.domain
"""
_DOMAIN_URLS_SQL = f"""
    SELECT citation.domain, count(DISTINCT citation.url)
    {_CITED_FROM_SQL}
        AND citation.domain = ANY(%s) AND citation.url <> ''
    GROUP BY citation.domain
"""
# A URL without a host has no domain to rank under, and a host cited after the stored URLs has no URL.
_PAGES_SQL = f"""
    SELECT citation.url, citation.domain, count(DISTINCT citation.citation_check_id)
    {_CITED_FROM_SQL}
        AND citation.domain <> '' AND citation.url <> ''
    GROUP BY citation.url, citation.domain
    ORDER BY count(DISTINCT citation.citation_check_id) DESC, citation.url
    LIMIT %s
"""


@lru_cache(maxsize=4096)
def registrable_domain(host: str) -> str:
    parts = _DOMAIN_PARTS(host)
    return parts.top_domain_under_public_suffix or host


def get_rankings(
    team_id: int, *, target_domains: list[str], timezone_name: str, window: CheckWindow, scope: CheckScope
) -> PromptSetRankings:
    window_from, window_to = window.window_from, window.window_to
    window_start, previous_start, until = window.start, window.previous_start, window.until
    answered = AEOCitationCheck.objects.for_team(team_id).filter(
        scope_filter(scope),
        created_at__gte=window_start,
        created_at__lt=until,
        check_failed=False,
        mode=CheckMode.WEB_SEARCH,
    )
    answers = answered.count()

    # A target like docs.example.com stands for the whole example.com brand.
    targets = {registrable_domain(domain.lower()) for domain in target_domains}
    scope_params = scope_sql_params(scope)
    citations = _Citations(
        resolve_effective_team_id(team_id), since=window_start, until=until, scope_params=scope_params
    )
    ranked_domains = citations.ranked_domains()
    # Competitors a person confirmed in the brand catalog win; until there are any, derive them from citations.
    # Our own domains always rank as the target, even when someone labeled one a competitor.
    confirmed = {domain: name for domain, name in _confirmed_competitors(team_id).items() if domain not in targets}
    catalog_ids = _catalog_brand_ids(team_id)
    # Each competitor ranks by its catalog brand, so a domain the catalog does not have yet waits for the sync.
    competitors = list(confirmed) or _competitors(
        [(domain, count) for domain, count in ranked_domains if domain in catalog_ids],
        targets,
        brand_names(target_domains),
        catalog_excluded=_catalog_exclusions(team_id),
    )
    names = {domain: confirmed[domain] if domain in confirmed else _brand_name(domain) for domain in competitors}
    top_domains = ranked_domains[:MAX_RANKED_DOMAINS]
    domain_urls = citations.urls_per_domain([domain for domain, _ in top_domains])
    target_domain = registrable_domain(target_domains[0].lower()) if target_domains else None
    # Every own brand ranks as the one target, whatever domain it is on.
    own_ids = tuple(catalog_ids[domain] for domain in target_domains if domain in catalog_ids)
    brands = ([(target_domain, own_ids, True)] if target_domain else []) + [
        (domain, (catalog_ids[domain],), False) for domain in competitors if domain in catalog_ids
    ]
    brand_days = _brand_days(
        team_id,
        brands=brands,
        timezone_name=timezone_name,
        since=previous_start,
        until=until,
        window_from=window_from,
        scope=scope,
    )
    positive_share = _positive_share(answered) if target_domain else None

    ranked_brands = sorted(
        (
            RankedBrand(
                domain=domain,
                name=", ".join(brand_names(target_domains)) if is_target else names[domain],
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
        competitors_confirmed=bool(confirmed),
        days=window.days,
        window_from=window_from,
        window_to=window_to,
        branded=scope.segment,
        engine=scope.engine,
        topic=scope.topic,
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
    once per answer from the stored cited URL rows."""

    def __init__(self, team_id: int, *, since: dt.datetime, until: dt.datetime, scope_params: list[str | None]) -> None:
        self._params: list[Any] = [team_id, since, until, team_id, since, until, *scope_params]

    def ranked_domains(self) -> list[tuple[str, int]]:
        """Every cited registrable domain with the answers that cited it, most cited first."""
        with connection.cursor() as cursor:
            cursor.execute(_DOMAIN_ANSWERS_SQL, self._params)
            counts = dict(cursor.fetchall())
        return _ranked(counts, len(counts))

    def urls_per_domain(self, domains: list[str]) -> dict[str, int]:
        if not domains:
            return {}
        with connection.cursor() as cursor:
            cursor.execute(_DOMAIN_URLS_SQL, [*self._params, domains])
            return dict(cursor.fetchall())

    def top_pages(self) -> list[_CitedPage]:
        with connection.cursor() as cursor:
            cursor.execute(_PAGES_SQL, [*self._params, MAX_RANKED_PAGES])
            return [_CitedPage(url=url, domain=domain, answers=count) for url, domain, count in cursor.fetchall()]


def _confirmed_competitors(team_id: int) -> dict[str, str]:
    """Confirmed competitors from the brand catalog: their names by domain."""
    rows = (
        AEOBrand.objects.for_team(team_id)
        .filter(kind=BrandKind.COMPETITOR.value, status=BrandStatus.CONFIRMED.value)
        .order_by("domain")
        .values_list("domain", "name")[:MAX_RANKED_COMPETITORS]
    )
    return dict(rows)


def _catalog_brand_ids(team_id: int) -> dict[str, uuid.UUID]:
    return dict(AEOBrand.objects.for_team(team_id).values_list("domain", "id"))


def _catalog_exclusions(team_id: int) -> set[str]:
    """Domains a person ignored or confirmed as something other than a competitor, so the fallback skips them."""
    rows = AEOBrand.objects.for_team(team_id).filter(
        Q(status=BrandStatus.IGNORED.value)
        | (Q(status=BrandStatus.CONFIRMED.value) & ~Q(kind=BrandKind.COMPETITOR.value))
    )
    return set(rows.values_list("domain", flat=True))


def _competitors(
    ranked_domains: list[tuple[str, int]],
    targets: set[str],
    target_names: tuple[str, ...],
    *,
    catalog_excluded: set[str],
) -> list[str]:
    # The project's own brand on another domain (example.de for example.com) is not a competitor.
    excluded = NON_BRAND_NAMES | set(target_names)
    competitors: list[str] = []
    for domain, _ in ranked_domains:
        if len(competitors) == MAX_RANKED_COMPETITORS:
            break
        if domain not in targets and domain not in catalog_excluded and _brand_name(domain) not in excluded:
            competitors.append(domain)
    return competitors


def _brand_days(
    team_id: int,
    *,
    brands: list[tuple[str, tuple[uuid.UUID, ...], bool]],
    timezone_name: str,
    since: dt.datetime,
    until: dt.datetime,
    window_from: dt.date,
    scope: CheckScope,
) -> _BrandDays:
    current: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    previous: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    if not brands:
        return _BrandDays(current=current, previous=previous, daily=())
    pairs = [(brand_id, domain) for domain, brand_ids, _ in brands for brand_id in brand_ids]
    with connection.cursor() as cursor:
        cursor.execute(
            _BRAND_DAYS_SQL,
            {
                "timezone": timezone_name,
                # The ORM reads above map a child environment to its parent; raw SQL has to do the same.
                "team_id": resolve_effective_team_id(team_id),
                "since": since,
                "until": until,
                "brand_ids": [brand_id for brand_id, _ in pairs],
                "brand_domains": [domain for _, domain in pairs],
                "domains": [domain for domain, _, _ in brands],
                "target_domain": next((domain for domain, _, is_target in brands if is_target), None),
                **named_scope_sql_params(scope),
            },
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
