import enum
import time
import logging
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from typing import Self

from django.core.cache import cache

import dns.resolver
import dns.exception
from dns.rdtypes.ANY.MX import MX

from posthog.cloud_utils import is_cloud
from posthog.helpers.email_utils import email_domain
from posthog.security.oob_domains import matched_oob_domain

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_SECONDS = 0.3
CACHE_SECONDS = 60 * 60 * 24

# Bounded, so a burst of signups queues lookups, which run out of budget, instead of starting threads.
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="inbox-provider")


class InboxProvider(enum.StrEnum):
    # The frontend maps each value to a button label and a webmail URL, so a value is API.
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    MICROSOFT_365 = "microsoft_365"
    YAHOO = "yahoo"
    ICLOUD = "icloud"
    PROTON = "proton"


_INBOX_PROVIDERS_BY_DOMAIN: dict[str, InboxProvider] = {
    "gmail.com": InboxProvider.GMAIL,
    "googlemail.com": InboxProvider.GMAIL,
    "outlook.com": InboxProvider.OUTLOOK,
    "hotmail.com": InboxProvider.OUTLOOK,
    "hotmail.co.uk": InboxProvider.OUTLOOK,
    "live.com": InboxProvider.OUTLOOK,
    "msn.com": InboxProvider.OUTLOOK,
    "yahoo.com": InboxProvider.YAHOO,
    "yahoo.co.uk": InboxProvider.YAHOO,
    "ymail.com": InboxProvider.YAHOO,
    "icloud.com": InboxProvider.ICLOUD,
    "me.com": InboxProvider.ICLOUD,
    "mac.com": InboxProvider.ICLOUD,
    "proton.me": InboxProvider.PROTON,
    "protonmail.com": InboxProvider.PROTON,
    "pm.me": InboxProvider.PROTON,
}

# The leading dot anchors each suffix to a label boundary. Outlook.com consumer mail and Microsoft 365
# tenants open different webmail sites.
_INBOX_PROVIDERS_BY_MX_MARKER: tuple[tuple[str, InboxProvider], ...] = (
    (".google.com", InboxProvider.GMAIL),
    (".googlemail.com", InboxProvider.GMAIL),
    (".olc.protection.outlook.com", InboxProvider.OUTLOOK),
    (".mail.protection.outlook.com", InboxProvider.MICROSOFT_365),
    (".yahoodns.net", InboxProvider.YAHOO),
    (".mail.icloud.com", InboxProvider.ICLOUD),
    (".protonmail.ch", InboxProvider.PROTON),
)


def detect_inbox_provider(mx_host: str | None) -> InboxProvider | None:
    """The provider behind the primary MX host, the one with the lowest preference.

    Only the primary host counts, because a filtering gateway in front of the mailbox, such as a
    spam filter, receives the mail first and hides which webmail the address reads it in."""
    if not mx_host:
        return None
    anchored = "." + mx_host.lower().rstrip(".")
    for marker, provider in _INBOX_PROVIDERS_BY_MX_MARKER:
        if anchored.endswith(marker):
            return provider
    return None


def _primary_mx_host(domain: str) -> str | None:
    """None when the domain has no MX record. A failed lookup raises, so it is never cached."""
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=LOOKUP_TIMEOUT_SECONDS)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return None
    records = [rdata for rdata in answers if isinstance(rdata, MX)]
    return min(records, key=lambda rdata: rdata.preference).exchange.to_text() if records else None


def _cache_key(domain: str) -> str:
    return f"inbox_provider:{domain}"


def _resolve_and_cache(domain: str) -> InboxProvider | None:
    # Caching here keeps an answer that arrives after the caller stopped waiting.
    provider = detect_inbox_provider(_primary_mx_host(domain))
    try:
        cache.set(_cache_key(domain), provider or "", CACHE_SECONDS)
    except Exception:
        logger.warning("Could not cache the inbox provider", exc_info=True)
    return provider


class InboxProviderLookup:
    """Finds the webmail an address reads its mail in, while the caller sends it an email.

    Start the lookup before the send and read `result()` after it. The result is a hint for a
    button, so neither step raises: any failure reads as an unknown provider.
    """

    def __init__(
        self, resolved: InboxProvider | None = None, future: Future[InboxProvider | None] | None = None
    ) -> None:
        self._resolved = resolved
        self._future = future
        self._started_at = time.monotonic()

    @classmethod
    def start(cls, email: str) -> Self:
        domain = (email_domain(email) or "").strip().lower().rstrip(".")
        try:
            if provider := _INBOX_PROVIDERS_BY_DOMAIN.get(domain):
                return cls(resolved=provider)
            # Only Cloud runs the experiment that shows the button.
            if not domain or not is_cloud():
                return cls()
            cached = cache.get(_cache_key(domain))
            if cached is not None:
                return cls(resolved=InboxProvider(cached) if cached else None)
            if (oob_domain := matched_oob_domain(domain)) is not None:
                # Resolving the name would itself confirm the path to whoever runs the collaborator.
                logger.info("security.oob_domain_seen domain=%s guard=inbox_providers", oob_domain)
                return cls()
            return cls(future=_executor.submit(_resolve_and_cache, domain))
        except Exception:
            logger.warning("Could not start the inbox provider lookup", exc_info=True)
            return cls()

    def result(self) -> InboxProvider | None:
        if self._future is None:
            return self._resolved
        remaining = max(0.0, LOOKUP_TIMEOUT_SECONDS - (time.monotonic() - self._started_at))
        try:
            return self._future.result(timeout=remaining)
        except (FutureTimeoutError, dns.exception.DNSException):
            return None
        except Exception:
            logger.warning("Inbox provider lookup failed", exc_info=True)
            return None
