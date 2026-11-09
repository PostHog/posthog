"""Fills the team's brand catalog from the domains the answer engines cite."""

from __future__ import annotations

from urllib.parse import urlparse

from django.db.models import QuerySet

import tldextract

from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.engines import is_target_url, target_position
from products.aeo.backend.facade.contracts import (
    BRAND_DOMAIN_MAX_LENGTH,
    BRAND_NAME_MAX_LENGTH,
    BrandKind,
    BrandSource,
    BrandStatus,
    BrandSyncResult,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck

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
    """Recompute `cited`, `target_urls` and `target_best_position` of the team's answered checks from
    their stored citations and the team's current own domains, the same way the runner sets them.
    Returns how many checks changed.

    Two overlapping passes can each read a different set of own domains. A pass re-reads the domains
    when it ends and goes again if they moved, so the pass that writes last always used the current set.
    """
    team_id = resolve_effective_team_id(team_id)
    changed = 0
    domains = own_domains(team_id)
    while True:
        changed += _recompute_with(team_id, domains)
        current = own_domains(team_id)
        if current == domains:
            return changed
        domains = current


def _recompute_with(team_id: int, domains: list[str]) -> int:
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True)
    rows = checks.filter(check_failed=False).only("id", "cited_urls", "cited", "target_urls", "target_best_position")
    pending: list[AEOCitationCheck] = []
    changed = 0
    for check in rows.iterator(chunk_size=RECOMPUTE_BATCH_SIZE):
        cited_urls = [url for url in check.cited_urls or [] if isinstance(url, str)]
        target_urls = [url for url in cited_urls if is_target_url(url, domains)]
        position = target_position(cited_urls, domains)
        if (check.cited, check.target_urls, check.target_best_position) == (bool(target_urls), target_urls, position):
            continue
        check.cited = bool(target_urls)
        check.target_urls = target_urls
        check.target_best_position = position
        # The score was taken for the brand as it was then. The next sentiment run scores a cleared row
        # again when it names the current brand and falls inside the run's backlog window.
        check.brand_sentiment = None
        check.brand_sentiment_score = None
        pending.append(check)
        if len(pending) >= RECOMPUTE_BATCH_SIZE:
            changed += _write_recomputed(checks, pending)
            pending = []
    return changed + _write_recomputed(checks, pending)


def _write_recomputed(checks: QuerySet[AEOCitationCheck], rows: list[AEOCitationCheck]) -> int:
    checks.bulk_update(
        rows, ["cited", "target_urls", "target_best_position", "brand_sentiment", "brand_sentiment_score"]
    )
    return len(rows)


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
    return BrandSyncResult(domains=len(domains), created=len(new_brands))
