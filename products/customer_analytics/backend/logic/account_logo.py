from collections.abc import Iterable

from products.customer_analytics.backend.domain import parse_company_domain


def resolve_logo_domain(
    *,
    website_domain: str | None,
    email_domains: Iterable[str],
    external_id: str | None,
) -> str | None:
    for candidate in (website_domain, *email_domains, external_id):
        domain = parse_company_domain(candidate)
        if domain:
            return domain
    return None
