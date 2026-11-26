from collections.abc import Iterable
from itertools import islice, zip_longest

from products.customer_analytics.backend.domain import parse_company_domain
from products.customer_analytics.backend.models import Account


def resolve_logo_domain(*, website_domain: str | None, email_domains: Iterable[str]) -> str | None:
    if website_domain:
        return website_domain

    for email_domain in email_domains:
        domain = parse_company_domain(email_domain)
        if domain:
            return domain
    return None


def list_logo_domains_across_teams(*, limit: int, per_team_limit: int) -> list[str]:
    """Account logo domains across all teams, for jobs that prepare per-domain assets such as
    favicons. Resolved the same way as the accounts table's `logo_domain`, so a cached asset is keyed
    by the hostname the frontend asks for. Each team adds at most `per_team_limit` domains, newest
    accounts first, and the teams take turns in the list, so one team cannot crowd out the rest."""
    team_domains: dict[int, list[str]] = {}
    seen: set[str] = set()
    rows = Account.objects.unscoped().order_by("-created_at").values_list("team_id", "_properties")
    for team_id, stored in rows.iterator(chunk_size=2000):
        domains = team_domains.setdefault(team_id, [])
        if len(domains) >= per_team_limit:
            continue
        stored = stored or {}
        website_domain = stored.get("website_domain")
        email_domains = stored.get("email_domains")
        domain = resolve_logo_domain(
            website_domain=website_domain if isinstance(website_domain, str) else None,
            email_domains=[d for d in email_domains if isinstance(d, str)] if isinstance(email_domains, list) else [],
        )
        if not domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
    interleaved = (domain for turn in zip_longest(*team_domains.values()) for domain in turn if domain is not None)
    return list(islice(interleaved, limit))
