import json
from functools import lru_cache
from pathlib import Path

import structlog

from posthog.security.url_validation import canonicalize_host

logger = structlog.get_logger(__name__)

_DOMAINS_PATH = Path(__file__).parent / "crosslang" / "oob_domains.json"


@lru_cache(maxsize=1)
def oob_domains() -> frozenset[str]:
    """The out-of-band interaction domains, read once.

    Detection must never break traffic, so a missing or malformed file matches nothing. When this
    list starts refusing hosts, this read has to fail closed instead.
    """
    try:
        raw = json.loads(_DOMAINS_PATH.read_text())
        return frozenset(domain.lower() for domain in raw["domains"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.exception("security.oob_domains_unavailable", error=str(error))
        return frozenset()


def matched_oob_domain(host: str) -> str | None:
    """The listed domain this host belongs to, or None."""
    if not host or "@" in host or "/" in host:
        # The guards hand us a parsed hostname. Anything else is a raw URL or a credential, and
        # matching it would put that string in the log line.
        return None
    canonical = canonicalize_host(host)
    for domain in oob_domains():
        if canonical == domain or canonical.endswith(f".{domain}"):
            return domain
    return None
