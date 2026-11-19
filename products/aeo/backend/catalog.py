"""Fills the team's brand catalog from the domains the answer engines cite."""

from __future__ import annotations

import uuid
import datetime as dt
from collections import Counter, defaultdict
from urllib.parse import urlparse

from django.db import connection
from django.db.models import QuerySet
from django.utils import timezone

import tldextract

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.brand import SEGMENT_SQL, brand_names, branded_filter, names_brand, segment_sql_params
from products.aeo.backend.engines import is_target_url, own_domains_key, target_position
from products.aeo.backend.facade.contracts import (
    BRAND_DOMAIN_MAX_LENGTH,
    BRAND_NAME_MAX_LENGTH,
    COMPETITOR_CANDIDATE_DAYS,
    BrandedSegment,
    BrandKind,
    BrandSource,
    BrandStatus,
    BrandSyncResult,
    CompetitorCandidate,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck
from products.aeo.backend.rankings import word_pattern
from products.aeo.backend.stored_results import bump_data_version_on_commit

# Community, review and media sites that engines cite for every topic. They are sources, not companies we compete with.
PUBLISHER_DOMAINS = frozenset(
    {
        "reddit.com",
        "youtube.com",
        "g2.com",
        "capterra.com",
        "github.com",
        "medium.com",
        "stackoverflow.com",
        "wikipedia.org",
        "linkedin.com",
        "x.com",
        "twitter.com",
        "quora.com",
        "dev.to",
        "producthunt.com",
        "news.ycombinator.com",
    }
)
RECOMPUTE_BATCH_SIZE = 1000
# How many cited brands a competitor candidates request matches names against, whatever the catalog holds.
MAX_COMPETITOR_CANDIDATE_BRANDS = 200
# Each pass scans the team's stale checks; edits that keep landing are left to the next reconcile.
RECOMPUTE_MAX_PASSES = 3
# Offline: the bundled public suffix list, so a sync never fetches anything.
_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())


def registrable_domain(url: str) -> str | None:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return None
    parts = _DOMAIN_PARTS(host.lower())
    # news.ycombinator.com is a site of its own; every other subdomain belongs to its registrable domain.
    domain = host.lower() if host.lower() in PUBLISHER_DOMAINS else parts.top_domain_under_public_suffix
    # Cited URLs come from third-party pages; a host longer than the column would fail the whole bulk insert.
    if not domain or len(domain) > BRAND_DOMAIN_MAX_LENGTH:
        return None
    return domain


def placeholder_name(domain: str) -> str:
    label = _DOMAIN_PARTS(domain).domain or domain
    return label[:1].upper() + label[1:BRAND_NAME_MAX_LENGTH]


def own_domains(team_id: int) -> list[str]:
    """The registrable domains that count as the team itself: its own brands that nobody ignored, sorted."""
    return sorted(
        AEOBrand.objects.for_team(team_id)
        .filter(kind=BrandKind.OWN)
        .exclude(status=BrandStatus.IGNORED)
        .values_list("domain", flat=True)
    )


def counts_as_own(kind: str, status: str) -> bool:
    return kind == BrandKind.OWN and status != BrandStatus.IGNORED


def recompute_own_citations(team_id: int) -> int:
    """Recompute `cited`, `target_urls` and `target_best_position` of the team's answered checks whose
    own domains key is not the current one, from their stored citations, the same way the runner sets them.
    Returns how many checks changed.

    A pass re-reads the domains when it ends and goes again if they moved, up to `RECOMPUTE_MAX_PASSES`.
    Whatever a pass leaves stale keeps its old key, so the reconcile after the next citation run repairs it.
    """
    team_id = resolve_effective_team_id(team_id)
    changed = 0
    domains = own_domains(team_id)
    for _ in range(RECOMPUTE_MAX_PASSES):
        recomputed = _recompute_with(team_id, domains)
        changed += recomputed.changed
        key = own_domains_key(domains)
        failed_on_another_key = _failed_checks_on_another_key(team_id, key)
        _recompute_branded_prompts(team_id, domains, whole_history=recomputed.rekeyed or bool(failed_on_another_key))
        # Only the checks read before the prompt pass get the key. A failed check that a run records
        # meanwhile keeps its own, so the next reconcile still sees it.
        AEOCitationCheck.objects.for_team(team_id, canonical=True).filter(id__in=failed_on_another_key).update(
            own_domains_key=key
        )
        current = own_domains(team_id)
        if current == domains:
            break
        domains = current
    bump_data_version_on_commit(team_id)
    return changed


def _failed_checks_on_another_key(team_id: int, key: str) -> list[uuid.UUID]:
    """Failed checks keyed for other own domains. A failed check has no citations to recompute, so the
    citation pass leaves its key alone, and it still shows a change of the own domains when no answered
    check does. The failed checks are found in the window index first, so only their rows are loaded."""
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True)
    failed = list(checks.filter(check_failed=True).values_list("id", flat=True))
    return list(checks.filter(id__in=failed).exclude(own_domains_key=key).values_list("id", flat=True))


@frozen
class _Recomputed:
    changed: int
    # A check carried the key of other own domains, so the own domains changed since the last reconcile.
    rekeyed: bool


def _recompute_branded_prompts(team_id: int, domains: list[str], *, whole_history: bool) -> None:
    """Set `prompt_branded` on the checks of the team, failed ones included, because the branded split
    counts them too. The runner stores it against the own domains of the moment, so the whole history is
    read again only when those changed. Otherwise only the checks that have none are read, from the
    window index. Only the rows on the wrong side are written."""
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True)
    if not whole_history:
        checks = checks.filter(prompt_branded__isnull=True)
    branded = branded_filter(domains)
    checks.filter(branded).exclude(prompt_branded=True).update(prompt_branded=True)
    checks.exclude(branded).exclude(prompt_branded=False).update(prompt_branded=False)


def _recompute_with(team_id: int, domains: list[str]) -> _Recomputed:
    key = own_domains_key(domains)
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True)
    # exclude() keeps the null keys of checks recorded before the key existed. A check on the current
    # key that has no `names_brand` yet was recorded before that column existed, and is filled here too.
    stale = (
        checks.filter(check_failed=False)
        .exclude(own_domains_key=key, names_brand__isnull=False)
        .only("id", "cited_urls", "cited", "target_urls", "target_best_position", "own_domains_key", "answer_text")
        .order_by("id")
    )
    changed = 0
    rekeyed = False
    last_id = None
    # Keyset pages with a database limit: behind PgBouncer, iterator() would buffer the whole result.
    while page := list((stale.filter(id__gt=last_id) if last_id else stale)[:RECOMPUTE_BATCH_SIZE]):
        last_id = page[-1].id
        rescored: list[AEOCitationCheck] = []
        kept: list[AEOCitationCheck] = []
        for check in page:
            citations_moved = _recompute_check(check, domains)
            check.names_brand = names_brand(check.answer_text, domains)
            # A check keyed for other own brands was scored for them, even when its citations match both.
            # A check from before the key existed was scored for the domains it was cited against.
            # A check already on the current key is only here to get its `names_brand`.
            if check.own_domains_key != key and (check.own_domains_key is not None or citations_moved):
                # The next sentiment run scores a cleared check again when it names the current brand and
                # falls inside the run's backlog window.
                check.brand_sentiment = None
                check.brand_sentiment_score = None
                check.brand_sentiment_sentences = None
                rescored.append(check)
            else:
                kept.append(check)
            rekeyed = rekeyed or check.own_domains_key != key
            check.own_domains_key = key
            changed += citations_moved
        _write_recomputed(checks, rescored, kept)
    return _Recomputed(changed=changed, rekeyed=rekeyed)


def _recompute_check(check: AEOCitationCheck, domains: list[str]) -> bool:
    """Set the citation fields of one check from its stored citations, and return whether they moved."""
    cited_urls = [url for url in check.cited_urls or [] if isinstance(url, str)]
    # The runner stores the first MAX_URLS_PER_CHECK citations, but takes the target URLs from the full
    # list, so a target URL missing from `cited_urls` was cited further down and still counts.
    beyond = [url for url in check.target_urls or [] if isinstance(url, str) and url not in cited_urls]
    target_urls = [url for url in [*cited_urls, *beyond] if is_target_url(url, domains)]
    position = target_position(cited_urls, domains)
    if position is None and target_urls:
        # Only a citation past the stored ones matches. Its exact position is known only when it was the
        # best one before too.
        stored = check.target_best_position
        position = stored if stored is not None and stored > len(cited_urls) else None
    moved = (check.cited, check.target_urls, check.target_best_position) != (bool(target_urls), target_urls, position)
    check.cited = bool(target_urls)
    check.target_urls = target_urls
    check.target_best_position = position
    return moved


_CITATION_FIELDS = ["cited", "target_urls", "target_best_position", "own_domains_key", "names_brand"]
_SENTIMENT_FIELDS = ["brand_sentiment", "brand_sentiment_score", "brand_sentiment_sentences"]


def _write_recomputed(
    checks: QuerySet[AEOCitationCheck], rescored: list[AEOCitationCheck], kept: list[AEOCitationCheck]
) -> None:
    checks.bulk_update(rescored, [*_CITATION_FIELDS, *_SENTIMENT_FIELDS])
    # Sentiment is left out, so a score written meanwhile for these checks survives.
    checks.bulk_update(kept, _CITATION_FIELDS)


# A newly cited domain is never the team's own: own brands are added by people before the first run.
def _classify(domain: str) -> tuple[BrandKind, BrandStatus]:
    if domain in PUBLISHER_DOMAINS:
        return BrandKind.PUBLISHER, BrandStatus.CONFIRMED
    return BrandKind.UNKNOWN, BrandStatus.SUGGESTED


def sync_brands_from_run(team_id: int, run_id: str) -> BrandSyncResult:
    """Add every domain the run's answers cited that the catalog does not have yet.

    Only inserts: name, kind, status and aliases of existing brands belong to people, and citation counts are
    computed when they are read, so nothing here goes stale.
    """
    # bulk_create skips the save() that rewrites a child environment to its parent, so resolve it here.
    team_id = resolve_effective_team_id(team_id)
    cited = (
        AEOCitationCheck.objects.for_team(team_id, canonical=True)
        .filter(run_id=run_id, check_failed=False)
        .values_list("cited_urls", flat=True)
    )
    domains = {
        domain
        for cited_urls in cited
        for url in cited_urls or []
        if isinstance(url, str) and (domain := registrable_domain(url))
    }
    known = set(
        AEOBrand.objects.for_team(team_id, canonical=True).filter(domain__in=domains).values_list("domain", flat=True)
    )
    new_brands = []
    for domain in sorted(domains - known):
        kind, status = _classify(domain)
        new_brands.append(
            AEOBrand(
                team_id=team_id,
                name=placeholder_name(domain),
                domain=domain,
                kind=kind,
                status=status,
                source=BrandSource.CITATIONS,
            )
        )
    # A concurrent sync may insert the same domain first; its row wins.
    AEOBrand.objects.for_team(team_id, canonical=True).bulk_create(new_brands, ignore_conflicts=True)
    bump_data_version_on_commit(team_id)
    return BrandSyncResult(domains=len(domains), created=len(new_brands))


# Hosts the window's answers cite, counted in one pass over them. Brand matching reads this list rather than the
# answers, so a catalog that keeps growing never makes a request scan them again for every brand it holds.
_CITED_HOSTS_SQL = f"""
    SELECT lower(host), count(*)
    FROM posthog_aeo_citation_check AS check_row,
        jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(check_row.top_cited_domains) = 'array' THEN check_row.top_cited_domains ELSE '[]'::jsonb END
        ) AS host
    WHERE check_row.team_id = %s AND check_row.created_at >= %s AND check_row.check_failed = false
        AND {SEGMENT_SQL}
    GROUP BY 1
"""

# Answers to non-branded prompts that cite each candidate's hosts, and answers whose text has one of the brand's
# names as a word. The cited hosts arrive already mapped to their brand, so both stages join by equality and only
# the capped set of cited brands reaches the regex. Placeholder names are often common words, so a match needs
# both signals.
_COMPETITOR_CANDIDATES_SQL = f"""
    WITH answered AS MATERIALIZED (
        SELECT check_row.id, check_row.answer_text, check_row.top_cited_domains
        FROM posthog_aeo_citation_check AS check_row
        WHERE check_row.team_id = %s AND check_row.created_at >= %s AND check_row.check_failed = false
            AND {SEGMENT_SQL}
    ),
    citing AS (
        SELECT mapping.domain, count(DISTINCT answered.id) AS answers
        FROM answered
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(answered.top_cited_domains) = 'array' THEN answered.top_cited_domains ELSE '[]'::jsonb END
        ) AS cited_host
        JOIN unnest(%s::text[], %s::text[]) AS mapping(host, domain) ON lower(cited_host) = mapping.host
        GROUP BY mapping.domain
    ),
    counted AS (
        SELECT citing.domain, citing.answers AS citing,
            count(*) FILTER (WHERE answered.answer_text ~* brand.pattern) AS naming
        FROM citing
        JOIN unnest(%s::text[], %s::text[]) AS brand(domain, pattern) ON brand.domain = citing.domain
        CROSS JOIN answered
        GROUP BY citing.domain, citing.answers
    )
    SELECT domain, naming, citing
    FROM counted
    WHERE naming > 0
    ORDER BY least(naming, citing) DESC, greatest(naming, citing) DESC, domain
    LIMIT %s
"""


def _brand_domains(host: str, domains: set[str]) -> list[str]:
    """The candidate domains a cited host belongs to: the host itself, and every domain it sits under."""
    labels = host.split(".")
    return [suffix for index in range(len(labels)) if (suffix := ".".join(labels[index:])) in domains]


@frozen
class _CitedBrandHosts:
    """The window's cited hosts and the candidate brand each one belongs to, as the arrays the query unnests."""

    hosts: list[str]
    domains: list[str]


def _cited_brand_hosts(rows: list[tuple[str, int]], domains: set[str]) -> _CitedBrandHosts:
    """The cited hosts of the `MAX_COMPETITOR_CANDIDATE_BRANDS` most cited candidates.

    Citations bound a candidate's rank, because it ranks by the smaller of its two counts, so the cap keeps the
    brands that can rank highest. It is still an approximation: a brand below the cap outranks one above it when
    enough of the brands above score no name match at all. Bounding the regex is worth that, because without the
    cap one request's cost follows how many domains the window cites."""
    hosts: dict[str, list[str]] = defaultdict(list)
    citations: Counter[str] = Counter()
    for host, answers in rows:
        for domain in _brand_domains(host, domains):
            hosts[domain].append(host)
            citations[domain] += answers
    top = sorted(hosts, key=lambda domain: (-citations[domain], domain))[:MAX_COMPETITOR_CANDIDATE_BRANDS]
    pairs = [(host, domain) for domain in top for host in hosts[domain]]
    return _CitedBrandHosts(hosts=[host for host, _ in pairs], domains=[domain for _, domain in pairs])


def competitor_candidates(team_id: int, *, limit: int) -> list[CompetitorCandidate]:
    """Suggested brands that answers to non-branded prompts in the last `COMPETITOR_CANDIDATE_DAYS` days both
    name and cite, ranked by the weaker of the two counts. Reads stored checks only."""
    team_id = resolve_effective_team_id(team_id)
    own = own_domains(team_id)
    # The project's own brand on another domain (example.de for example.com) is not a competitor.
    own_names = set(brand_names(own))
    suggested = (
        AEOBrand.objects.for_team(team_id)
        .filter(status=BrandStatus.SUGGESTED)
        .exclude(kind=BrandKind.OWN)
        .exclude(domain__in=own)
        .only("id", "name", "domain", "aliases")
    )
    brands: dict[str, AEOBrand] = {}
    patterns: dict[str, str] = {}
    for brand in suggested:
        names = tuple(name for name in [brand.name, *(brand.aliases or [])] if isinstance(name, str) and name.strip())
        if names and brand.name.strip().lower() not in own_names:
            brands[brand.domain] = brand
            patterns[brand.domain] = word_pattern(names)
    if not brands:
        return []
    since = timezone.now() - dt.timedelta(days=COMPETITOR_CANDIDATE_DAYS)
    segment = segment_sql_params(BrandedSegment.NON_BRANDED)
    with connection.cursor() as cursor:
        cursor.execute(_CITED_HOSTS_SQL, [team_id, since, *segment])
        cited_hosts = _cited_brand_hosts(cursor.fetchall(), set(brands))
        if not cited_hosts.domains:
            return []
        cited = sorted(set(cited_hosts.domains))
        cursor.execute(
            _COMPETITOR_CANDIDATES_SQL,
            [
                team_id,
                since,
                *segment,
                cited_hosts.hosts,
                cited_hosts.domains,
                cited,
                [patterns[domain] for domain in cited],
                limit,
            ],
        )
        rows = cursor.fetchall()
    return [
        CompetitorCandidate(
            brand_id=str(brands[domain].id),
            name=brands[domain].name,
            domain=domain,
            answers_naming=naming,
            answers_citing=citing,
        )
        for domain, naming, citing in rows
    ]
