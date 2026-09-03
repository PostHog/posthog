import re
from urllib.parse import urlsplit

from free_email_domains import whitelist as free_email_domains

_HOSTNAME_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_DOMAIN_LENGTH = 253
_MAILBOX_PROVIDER_DOMAINS = frozenset(free_email_domains) | {"proton.me"}


def parse_company_domain(raw: str | None) -> str | None:
    if not raw:
        return None

    value = raw.strip().lower().removeprefix("@")
    if not value:
        return None

    url_value = value if "://" in value or value.startswith("//") else f"//{value}"
    try:
        host = urlsplit(url_value).hostname
    except ValueError:
        return None

    if not host:
        return None

    host = host.rstrip(".").removeprefix("www.")
    if len(host) > _MAX_DOMAIN_LENGTH or not _HOSTNAME_RE.match(host):
        return None

    return None if host in _MAILBOX_PROVIDER_DOMAINS else host
