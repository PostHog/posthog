"""Fills the team's brand catalog from the domains the answer engines cite."""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings

import tldextract

from posthog.models.scoping.manager import resolve_effective_team_id

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


def _classify(domain: str, own_domains: set[str]) -> tuple[BrandKind, BrandStatus]:
    if domain in own_domains:
        return BrandKind.OWN, BrandStatus.CONFIRMED
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
    own_domains = {domain for target in settings.AEO_TARGET_DOMAINS if (domain := registrable_domain(f"//{target}"))}
    new_brands = []
    for domain in sorted(domains - known):
        kind, status = _classify(domain, own_domains)
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
