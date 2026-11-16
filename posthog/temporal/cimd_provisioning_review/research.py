"""Collects public web evidence about a partner's domain through Firecrawl, for Jev's second look.

A fixed set of calls rather than an agent: one homepage scrape and two searches per review, so
the cost of a review is known up front and the evidence Jev saw is stored whole on the review.
"""

from typing import Any

from requests import RequestException

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
    title: str | None = None
    description: str | None = None
    excerpt: str | None = None


@frozen
class ResearchEvidence:
    homepage: Homepage
    about_the_domain: FirecrawlSearch
    abuse_reports: FirecrawlSearch

    def to_json(self) -> dict[str, Any]:
        return {
            "homepage": {
                "url": self.homepage.url,
                "reachable": self.homepage.reachable,
                "final_url": self.homepage.final_url,
                "status_code": self.homepage.status_code,
                "title": self.homepage.title,
                "description": self.homepage.description,
                "excerpt": self.homepage.excerpt,
            },
            "search_results_about_the_domain": _results(self.about_the_domain),
            "search_results_for_abuse_reports": _results(self.abuse_reports),
        }


def _results(found: FirecrawlSearch) -> list[dict[str, str | None]]:
    return [{"url": r.url, "title": r.title, "description": r.description} for r in found.results]


def _scrape_homepage(url: str) -> Homepage:
    try:
        page = scrape(url, source=EGRESS_SOURCE, formats=("markdown",), priority=Priority.BATCH)
    except (FirecrawlScrapeFailed, RequestException):
        # A domain with no working site is evidence in itself, so this is reported, not retried.
        return Homepage(url=url, reachable=False)
    return Homepage(
        url=url,
        reachable=True,
        final_url=page.final_url,
        status_code=page.status_code,
        title=page.title,
        description=page.description,
        excerpt=page.markdown[:HOMEPAGE_EXCERPT_CHARS] if page.markdown else None,
    )


def research_domain(domain: str, *, homepage_url: str) -> ResearchEvidence:
    """Raises ``FirecrawlNotConfigured``, ``FirecrawlEgressBudgetExhausted`` and
    ``FirecrawlSearchFailed``; the activity decides which of them to retry."""
    return ResearchEvidence(
        homepage=_scrape_homepage(homepage_url),
        about_the_domain=search(f'"{domain}"', source=EGRESS_SOURCE, limit=SEARCH_RESULTS, priority=Priority.BATCH),
        abuse_reports=search(
            f'"{domain}" phishing OR scam OR fraud OR malware',
            source=EGRESS_SOURCE,
            limit=SEARCH_RESULTS,
            priority=Priority.BATCH,
        ),
    )
