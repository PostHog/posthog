"""Resolve the brand domain an account's logo is rendered from.

Nothing in the product asks a team to record a customer's website, so the domain is derived
from what teams already keep: the canonical "Domain" custom property (usually synced from a
CRM column), the matching domains behind meeting and email attribution, or a group key that
is already a hostname. An account no source covers renders a lettermark instead.
"""

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from free_email_domains import whitelist as _free_email_domains

# Dot-separated LDH labels, lowercase — the shape logo.dev is keyed on. Mirrors _DOMAIN_RE in
# posthog/cdp/services/icons.py (kept as a copy: importing it would drag the egress/requests
# stack into the facade import path). Values reach here from CRM columns and hand-typed fields,
# so anything else resolves to no logo rather than a request.
_HOSTNAME_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_DOMAIN_LENGTH = 253

# The account custom property the logo reads, matched case-insensitively. Deliberately not a
# canonical property: that flag means PostHog owns the value and locks the definition, whereas
# this one is the team's — theirs to rename away, retype, or point at any warehouse column.
LOGO_DOMAIN_PROPERTY_NAME = "Domain"

# Hosts that name a mailbox provider rather than a customer. A contact on a personal address
# would otherwise put a webmail logo on the account row, which reads as a data bug. The
# supplement covers providers the package hasn't picked up yet.
_MAILBOX_PROVIDER_DOMAINS = frozenset(_free_email_domains) | {"proton.me"}


def normalize_logo_domain(raw: str | None) -> str | None:
    """Reduce a stored value to the bare hostname, or None when it isn't one.

    Accepts what teams actually put in a website column — full URLs, bare hostnames, and
    ``@domain`` email suffixes — and strips the parts that would fork the icon cache
    (scheme, path, port, ``www.``, trailing dot, case).
    """
    if not raw:
        return None
    value = raw.strip().lower().removeprefix("@")
    if not value:
        return None
    try:
        # Prefix unschemed values so urlsplit reads the host; "example.com//path" has a "//" but
        # no scheme, and without the prefix it would parse entirely as a path.
        host = urlsplit(value if "://" in value or value.startswith("//") else f"//{value}").hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".").removeprefix("www.")
    if len(host) > _MAX_DOMAIN_LENGTH or not _HOSTNAME_RE.match(host):
        return None
    return None if host in _MAILBOX_PROVIDER_DOMAINS else host


def resolve_logo_domain(
    *,
    domain_property: str | None,
    email_domains: Iterable[str],
    external_id: str | None,
) -> str | None:
    """Pick the first source that yields a usable hostname.

    The custom property wins because a team populated it to name the company; the matching
    domains come next; the group key is a last resort for teams that key groups by hostname.
    """
    for candidate in (domain_property, *email_domains, external_id):
        domain = normalize_logo_domain(candidate)
        if domain:
            return domain
    return None
