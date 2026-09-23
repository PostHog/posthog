from collections.abc import Iterable

from products.customer_analytics.backend.domain import parse_company_domain


def resolve_logo_domain(*, website_domain: str | None, email_domains: Iterable[str]) -> str | None:
    if website_domain:
        return website_domain

    for email_domain in email_domains:
        domain = parse_company_domain(email_domain)
        if domain:
            return domain
    return None
