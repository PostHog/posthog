import json
from functools import lru_cache
from pathlib import Path

import structlog

from posthog.security.url_validation import canonicalize_host

logger = structlog.get_logger(__name__)

_DOMAINS_PATH = Path(__file__).parent / "crosslang" / "oob_domains.json"

# What a guard tells the customer when it refuses one of these names. The guards share it so the
# wording cannot drift between the surfaces a customer configures a host on.
OOB_DOMAIN_REFUSAL = "This host belongs to a domain PostHog doesn't connect to. Use a host on a domain you control."


@lru_cache(maxsize=1)
def oob_domains() -> frozenset[str]:
    """The out-of-band interaction domains, read once.

    A missing or malformed file matches nothing, which leaves every guard on the IP checks it
    ran before this list existed. The file ships in the same tree as this module, so a read that
    fails means a broken image rather than a tampered list, and refusing every host on one would
    be the larger outage.
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
