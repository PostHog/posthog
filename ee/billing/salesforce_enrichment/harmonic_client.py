import asyncio
import logging
from typing import Any, Optional

from django.conf import settings

import aiohttp

from posthog.exceptions_capture import capture_exception

from .constants import (
    HARMONIC_BASE_URL,
    HARMONIC_COMPANY_ENRICHMENT_QUERY,
    HARMONIC_DOMAIN_VARIATIONS,
    HARMONIC_MAX_RETRIES,
    HARMONIC_REQUEST_TIMEOUT_SECONDS,
    HARMONIC_RETRY_BACKOFF_SECONDS,
    HARMONIC_RETRYABLE_STATUS_CODES,
)

logger = logging.getLogger(__name__)


def is_transient_network_error(exc: BaseException) -> bool:
    """Whether an exception is an expected, retryable network blip from the Harmonic API.

    Covers upstream connection drops (``ServerDisconnectedError`` and other
    ``ClientConnectionError`` subclasses), egress-proxy errors and upstream 5xx
    (``ClientHttpProxyError`` / ``ClientResponseError`` with a retryable status),
    and request timeouts. These resolve on retry and should not be reported as issues.
    """
    if isinstance(exc, aiohttp.ClientConnectionError | asyncio.TimeoutError):
        return True
    if isinstance(exc, aiohttp.ClientResponseError) and exc.status in HARMONIC_RETRYABLE_STATUS_CODES:
        return True
    return False


class AsyncHarmonicClient:
    """Async Harmonic API client with controlled concurrency.

    Enriches company domains using Harmonic's GraphQL API with:
    - 5 concurrent requests (configurable)
    - 30s timeout per request
    - Domain variation fallbacks (www., non-www)
    - Automatic session management via context manager

    Usage:
        async with AsyncHarmonicClient() as client:
            data = await client.enrich_company_by_domain("posthog.com")
    """

    def __init__(self):
        self.api_key = settings.HARMONIC_API_KEY
        if not self.api_key:
            raise ValueError("Missing Harmonic API key: HARMONIC_API_KEY")

        self.session: Optional[aiohttp.ClientSession] = None
        self._session_cm: Any = None

    async def __aenter__(self):
        """Async context manager entry - create session."""
        timeout = aiohttp.ClientTimeout(total=HARMONIC_REQUEST_TIMEOUT_SECONDS)
        self._session_cm = aiohttp.ClientSession(trust_env=True, timeout=timeout)
        self.session = await self._session_cm.__aenter__()
        return self

    async def __aexit__(self, *args):
        """Async context manager exit - close session."""
        if self._session_cm:
            await self._session_cm.__aexit__(*args)

    def _clean_domain(self, domain: str) -> str:
        """Clean domain name by removing protocols and www prefix."""
        return domain.lower().strip().removeprefix("https://").removeprefix("http://").removeprefix("www.")

    async def enrich_company_by_domain(self, domain: str) -> Optional[dict[str, Any]]:
        """Get company data from Harmonic API for a domain.

        Tries domain variations: example.com → www.example.com if first fails.

        Args:
            domain: Company domain (e.g., "posthog.com")

        Returns:
            Company data dict or None if not found
        """
        # Rate limiting: 5 requests per second
        await asyncio.sleep(0.2)
        domain = self._clean_domain(domain)

        # Try domain variations
        domain_variations = [f"{prefix}{domain}" if prefix else domain for prefix in HARMONIC_DOMAIN_VARIATIONS]

        for domain_variation in domain_variations:
            try:
                data = await self._post_enrichment_query(domain_variation)
            except Exception as e:
                # Transient network blips (proxy 502s, server disconnects, timeouts) are expected for
                # this batch job and already retried above — don't surface them as actionable issues.
                if not is_transient_network_error(e):
                    capture_exception(e)
                continue

            if "errors" in data:
                continue

            result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
            if result.get("companyFound"):
                return result.get("company")

        return None

    async def _post_enrichment_query(self, domain_variation: str) -> dict[str, Any]:
        """POST a single enrichment query, retrying transient network failures with backoff."""
        if self.session is None:
            raise RuntimeError("HTTP session not initialized. Use async context manager.")

        variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

        for attempt in range(HARMONIC_MAX_RETRIES + 1):
            try:
                async with self.session.post(
                    f"{HARMONIC_BASE_URL}/graphql",
                    params={"apikey": self.api_key},
                    json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": variables},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response.raise_for_status()
                    data: dict[str, Any] = await response.json()
                    return data
            except Exception as e:
                if attempt == HARMONIC_MAX_RETRIES or not is_transient_network_error(e):
                    raise
                backoff = HARMONIC_RETRY_BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "Transient Harmonic request error for %s (attempt %d/%d), retrying in %.1fs: %s",
                    domain_variation,
                    attempt + 1,
                    HARMONIC_MAX_RETRIES + 1,
                    backoff,
                    e,
                )
                await asyncio.sleep(backoff)

        raise AssertionError("unreachable")  # loop either returns or raises

    async def enrich_companies_batch(self, domains: list[str]) -> list[dict[str, Any] | None]:
        """Enrich multiple domains concurrently.

        Args:
            domains: List of company domains to enrich

        Returns:
            List of company data dicts (None for failed enrichments)
        """
        if not domains:
            return []

        tasks = [self.enrich_company_by_domain(domain) for domain in domains]

        results: list[dict[str, Any] | BaseException | None] = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, BaseException):
                capture_exception(result)

        return [None if isinstance(result, BaseException) else result for result in results]
