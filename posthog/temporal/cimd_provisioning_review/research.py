"""Collects public web evidence about a partner's domain through Firecrawl, for Jev's second look.

A fixed set of calls rather than an agent: one homepage scrape and three searches per review, so
the cost of a review is known up front and the evidence Jev saw is stored whole on the review.
"""

from typing import Any

from posthog.api.oauth.cimd import registrable_domain
from posthog.dataclasses import frozen
from posthog.egress.firecrawl import FirecrawlScrapeFailed, FirecrawlSearch, scrape, search
from posthog.egress.limiter.policies import Priority

EGRESS_SOURCE = "cimd_provisioning_review"
SEARCH_RESULTS = 5
HOMEPAGE_EXCERPT_CHARS = 3000


@frozen
class Homepage:
    url: str
    reachable: bool
    final_url: str | None = None
    status_code: int | None = None
    # Set when the page redirected to another registrable domain. Its content is dropped,
    # because another company's site says nothing about this client.
    redirected_to_domain: str | None = None
    title: str | None = None
    description: str | None = None
    excerpt: str | None = None


@frozen
class ResearchEvidence:
    homepage: Homepage
    about_the_client: FirecrawlSearch
    about_the_domain: FirecrawlSearch
    abuse_reports: FirecrawlSearch

    def to_json(self) -> dict[str, Any]:
        return {
            "homepage": {
                "url": self.homepage.url,
                "reachable": self.homepage.reachable,
                "final_url": self.homepage.final_url,
                "status_code": self.homepage.status_code,
                "redirected_to_domain": self.homepage.redirected_to_domain,
                "title": self.homepage.title,
                "description": self.homepage.description,
                "excerpt": self.homepage.excerpt,
            },
            "search_results_about_the_client": _results(self.about_the_client),
            "search_results_about_the_domain": _results(self.about_the_domain),
            "search_results_for_abuse_reports": _results(self.abuse_reports),
        }


def _results(found: FirecrawlSearch) -> list[dict[str, str | None]]:
    return [{"url": r.url, "title": r.title, "description": r.description} for r in found.results]


def _is_provider_failure(error: FirecrawlScrapeFailed) -> bool:
    """Only a rate limit. Firecrawl also answers 500 when the target site does not load, so a 5xx
    from a scrape is a finding about the site. An outage of Firecrawl itself fails the searches too,
    and those failures make Temporal retry the step."""
    return error.status_code == 429


def _scrape_homepage(url: str, *, domain: str) -> Homepage:
    """Raises when Firecrawl itself is failing, so Temporal retries the step. A page that Firecrawl
    could not load is a finding about the site and comes back as unreachable."""
    try:
        page = scrape(url, source=EGRESS_SOURCE, formats=("markdown",), priority=Priority.BATCH)
    except FirecrawlScrapeFailed as error:
        if _is_provider_failure(error):
            raise
        return Homepage(url=url, reachable=False, status_code=error.status_code)
    if page.status_code is not None and page.status_code >= 400:
        return Homepage(url=url, reachable=False, final_url=page.final_url, status_code=page.status_code)
    final_domain = registrable_domain(page.final_url) if page.final_url else domain
    if final_domain != domain:
        return Homepage(
            url=url,
            reachable=True,
            final_url=page.final_url,
            status_code=page.status_code,
            redirected_to_domain=final_domain or None,
        )
    return Homepage(
        url=url,
        reachable=True,
        final_url=page.final_url,
        status_code=page.status_code,
        title=page.title,
        description=page.description,
        excerpt=page.markdown[:HOMEPAGE_EXCERPT_CHARS] if page.markdown else None,
    )


def research_domain(domain: str, *, homepage_url: str, client_name: str) -> ResearchEvidence:
    """Raises ``FirecrawlNotConfigured``, ``FirecrawlEgressBudgetExhausted``, network errors, and
    Firecrawl's own failures; the activity decides which of them to retry."""
    return ResearchEvidence(
        homepage=_scrape_homepage(homepage_url, domain=domain),
        about_the_client=search(
            f'"{client_name[:200]}" {domain}', source=EGRESS_SOURCE, limit=SEARCH_RESULTS, priority=Priority.BATCH
        ),
        about_the_domain=search(f'"{domain}"', source=EGRESS_SOURCE, limit=SEARCH_RESULTS, priority=Priority.BATCH),
        abuse_reports=search(
            f'"{domain}" phishing OR scam OR fraud OR malware',
            source=EGRESS_SOURCE,
            limit=SEARCH_RESULTS,
            priority=Priority.BATCH,
        ),
    )
