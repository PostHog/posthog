"""Brand visibility against competitors, and the domains and pages the engines cite.

Competitors are not configured anywhere: they are the brands behind the domains the engines cite
most, minus the review sites, forums and social networks that answers cite for every brand.
"""

from __future__ import annotations

import re
import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Iterable
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

import tldextract

from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.brand import brand_names, brand_regex
from products.aeo.backend.facade.contracts import (
    PromptSetRankings,
    RankedBrand,
    RankedBrandDay,
    RankedDomain,
    RankedPage,
)
from products.aeo.backend.models import AEOCitationCheck

MAX_RANKED_COMPETITORS = 10
MAX_RANKED_DOMAINS = 20
MAX_RANKED_PAGES = 20

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
    WHERE check_row.team_id = %s AND check_row.created_at >= %s AND check_row.check_failed = false
    GROUP BY brand.domain, day
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

    answered = AEOCitationCheck.objects.for_team(team_id).filter(created_at__gte=window_start, check_failed=False)
    citations = _Citations.from_checks(answered.values_list("cited_urls", flat=True).iterator(chunk_size=2000))
    answers = citations.answers

    # A target like docs.example.com stands for the whole example.com brand.
    targets = {registrable_domain(domain.lower()) for domain in target_domains}
    competitors = citations.competitors(targets, brand_names(target_domains))
    target_domain = registrable_domain(target_domains[0].lower()) if target_domains else None
    brands = ([(target_domain, brand_regex(target_domains), True)] if target_domain else []) + [
        (domain, rf"\m{re.escape(_brand_name(domain))}\M", False) for domain in competitors
    ]
    current, previous, daily = _brand_days(
        team_id,
        brands=[brand for brand in brands if brand[1]],
        timezone_name=timezone_name,
        since=previous_start,
        window_from=window_from,
    )
    positive_share = _positive_share(answered) if target_domain else None

    ranked_brands = sorted(
        (
            RankedBrand(
                domain=domain,
                name=", ".join(brand_names(target_domains)) if is_target else _brand_name(domain),
                is_target=is_target,
                answers_mentioning=current[domain][1],
                visibility=_share(*current[domain]),
                previous_visibility=_share(*previous[domain]),
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
        daily=daily,
        top_domains=tuple(
            RankedDomain(
                domain=domain,
                answers=count,
                share_of_answers=count / answers,
                urls=len(citations.domain_urls[domain]),
                is_target=domain in targets,
                is_competitor=domain in competitors,
            )
            for domain, count in _ranked(citations.domains, MAX_RANKED_DOMAINS)
        ),
        top_pages=tuple(
            RankedPage(
                url=url,
                answers=count,
                share_of_answers=count / answers,
                is_target=citations.page_domains[url] in targets,
            )
            for url, count in _ranked(citations.pages, MAX_RANKED_PAGES)
        ),
    )


class _Citations:
    """Cited pages and registrable domains across answered checks, counted once per answer."""

    def __init__(self) -> None:
        self.answers = 0
        self.pages: Counter[str] = Counter()
        self.domains: Counter[str] = Counter()
        self.domain_urls: defaultdict[str, set[str]] = defaultdict(set)
        self.page_domains: dict[str, str] = {}

    @classmethod
    def from_checks(cls, cited_urls_per_check: Iterable[Any]) -> _Citations:
        citations = cls()
        for cited_urls in cited_urls_per_check:
            citations.add(cited_urls if isinstance(cited_urls, list) else [])
        return citations

    def add(self, cited_urls: list[object]) -> None:
        self.answers += 1
        domains: set[str] = set()
        pages: set[str] = set()
        for url in {url for url in cited_urls if isinstance(url, str) and url}:
            # Engines return the URLs, and one that doesn't parse would break every later read of it.
            try:
                host = (urlparse(url).hostname or "").lower()
            except ValueError:
                continue
            if host:
                domain = registrable_domain(host)
                domains.add(domain)
                pages.add(url)
                self.domain_urls[domain].add(url)
                self.page_domains[url] = domain
        self.pages.update(pages)
        self.domains.update(domains)

    def competitors(self, targets: set[str], target_names: tuple[str, ...]) -> list[str]:
        # The project's own brand on another domain (example.de for example.com) is not a competitor.
        excluded = NON_BRAND_NAMES | set(target_names)
        competitors: list[str] = []
        for domain, _ in _ranked(self.domains, len(self.domains)):
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
    window_from: dt.date,
) -> tuple[defaultdict[str, list[int]], defaultdict[str, list[int]], tuple[RankedBrandDay, ...]]:
    """Answers and mentions per brand in the current and previous windows, and per day in the current one."""
    current: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    previous: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    if not brands:
        return current, previous, ()
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
    return current, previous, tuple(sorted(daily, key=lambda row: (row.date, row.domain)))


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


def _ranked(counter: Counter[str], limit: int) -> list[tuple[str, int]]:
    # Ties break on the value, so the order is stable between two requests.
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
