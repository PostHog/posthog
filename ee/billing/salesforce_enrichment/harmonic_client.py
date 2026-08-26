import asyncio
from typing import Any, Optional

from django.conf import settings

import aiohttp

from posthog.exceptions_capture import capture_exception

from .constants import (
    HARMONIC_BASE_URL,
    HARMONIC_COMPANY_ENRICHMENT_QUERY,
    HARMONIC_DOMAIN_VARIATIONS,
    HARMONIC_REQUEST_TIMEOUT_SECONDS,
)


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
                variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

                if self.session is None:
                    raise RuntimeError("HTTP session not initialized. Use async context manager.")
                async with self.session.post(
                    f"{HARMONIC_BASE_URL}/graphql",
                    json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": variables},
                    # Key in a header, not a query param: aiohttp errors carry request_info.real_url,
                    # so a URL-borne key would leak into exception telemetry when a lookup raises.
                    headers={"Content-Type": "application/json", "apikey": self.api_key},
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if "errors" in data:
                        continue

                    result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                    if result.get("companyFound"):
                        company_data = result.get("company")
                        return company_data

            except Exception as e:
                capture_exception(e)
                continue

        return None

    async def enrich_company_by_domain_strict(self, domain: str) -> Optional[dict[str, Any]]:
        """Like enrich_company_by_domain, but distinguishes not-found from operational failure.

        Returns None for a genuine not-found: at least one domain variation returned a clean
        GraphQL response with companyFound false, and no variation found the company. A clean
        not-found is an authoritative Harmonic answer even when the other variation errored —
        raising in that mixed case let one failing variation exhaust the caller's retries and
        fail the whole lookup with no archive row. In practice that mixed case has been rare
        (a prod trace attributed almost all no-archive-row orgs to DB errors before the lookup,
        not to this path); the point of returning the miss is that every terminal outcome now
        leaves an archived row, and a row is what the recheck, the backfill, and the
        re-enrichment sweep act on — an activity failure feeds none of them.

        Operational failures on EVERY variation (network errors, non-2xx status, JSON decode,
        GraphQL errors) still re-raise, so callers retry and alert instead of mistaking an
        outage for a missing company. On the mixed path — a clean not-found suppressing a
        sibling error — the suppressed error is captured rather than discarded, since that is
        exactly the failure mode that let the original bug hide with no signal anywhere.
        """
        await asyncio.sleep(0.2)
        domain = self._clean_domain(domain)
        domain_variations = [f"{prefix}{domain}" if prefix else domain for prefix in HARMONIC_DOMAIN_VARIATIONS]

        last_error: Optional[Exception] = None
        last_error_variation: Optional[str] = None
        saw_clean_not_found = False
        for domain_variation in domain_variations:
            try:
                variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

                if self.session is None:
                    raise RuntimeError("HTTP session not initialized. Use async context manager.")
                async with self.session.post(
                    f"{HARMONIC_BASE_URL}/graphql",
                    json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": variables},
                    # Key in a header, not a query param: aiohttp errors carry request_info.real_url,
                    # so a URL-borne key would leak into exception telemetry when a lookup raises.
                    headers={"Content-Type": "application/json", "apikey": self.api_key},
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if "errors" in data:
                        raise RuntimeError(f"Harmonic GraphQL errors for {domain_variation}: {data['errors']}")

                    result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                    if result.get("companyFound"):
                        return result.get("company")
                    if result.get("companyFound") is False:
                        saw_clean_not_found = True
            except Exception as e:
                last_error = e
                last_error_variation = domain_variation
                continue

        if last_error is not None and not saw_clean_not_found:
            raise last_error
        if last_error is not None:
            capture_exception(last_error, {"domain": domain, "failed_variation": last_error_variation})
        return None

    async def get_company_by_urn(self, urn: str) -> Optional[dict[str, Any]]:
        """Resolve a Harmonic company URN (e.g. from relatedCompanies) via the REST profile endpoint.

        Returns None only for a genuine not-found (404). Other failures propagate — like
        enrich_company_by_domain_strict, this does not capture_exception; parent-company
        resolution is optional, so the caller decides whether to swallow the error.
        """
        company_id = urn.rsplit(":", 1)[-1]

        if self.session is None:
            raise RuntimeError("HTTP session not initialized. Use async context manager.")
        await asyncio.sleep(0.2)
        # Short cap: a single profile fetch, and it shares the signup activity's 90s budget with
        # the up-to-60s domain lookup — inheriting the session's 30s total would eat all headroom.
        async with self.session.get(
            f"{HARMONIC_BASE_URL}/companies/{company_id}",
            headers={"apikey": self.api_key},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            return await response.json()

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
