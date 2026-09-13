import time
import asyncio
from typing import Any, Optional

from django.conf import settings

import aiohttp

from posthog.dataclasses import frozen
from posthog.egress.harmonic.limiter import HARMONIC_WINDOW_SECONDS, admission_interval_harmonic, pace_seconds_harmonic
from posthog.egress.harmonic.transport import HarmonicEgressBudgetExhausted, harmonic_request
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception

from .constants import (
    HARMONIC_BASE_URL,
    HARMONIC_COMPANY_ENRICHMENT_QUERY,
    HARMONIC_DOMAIN_VARIATIONS,
    HARMONIC_REQUEST_TIMEOUT_SECONDS,
)


@frozen
class HarmonicCompanyLookup:
    """Result of a strict company lookup: the company payload plus its tracking URN.

    enrichment_urn is set on every not-found (the enrichment Harmonic just queued for this
    domain) and on a hit only when a refresh is pending; it is None on a fresh hit. On a
    miss seen across multiple domain variations, the first non-null URN wins.
    """

    company: Optional[dict[str, Any]]
    enrichment_urn: Optional[str]


# Harmonic documents this as the per-call cap on /enrichment_status URNs.
_ENRICHMENT_STATUS_BATCH_SIZE = 50

# Caps how many slow lookups can overlap. Admission pacing controls the request rate.
_ENRICH_MAX_CONCURRENT_LOOKUPS = 10
_ENRICH_MAX_ATTEMPTS = 3


class AsyncHarmonicClient:
    """Async Harmonic API client, gated and recorded through the Harmonic egress transport.

    Enriches company domains using Harmonic's GraphQL API with:
    - Every outbound call routed through posthog.egress.harmonic.transport.harmonic_request
    - 30s timeout per request (two endpoints override to a shorter cap; see their docstrings)
    - Domain variation fallbacks (www., non-www)
    - Automatic session management via context manager

    ``priority`` defaults to CRITICAL: the interactive callers (signup enrichment, the ICP
    re-enrichment sweep) run inside a 90-second Temporal activity budget and must never be
    starved or shed. The weekly bulk job passes ``Priority.BATCH`` explicitly so it yields to
    that traffic instead.

    Usage:
        async with AsyncHarmonicClient(priority=Priority.BATCH, source="my_job") as client:
            data = await client.enrich_company_by_domain("posthog.com")
    """

    def __init__(self, *, priority: Priority = Priority.CRITICAL, source: str = "harmonic_client") -> None:
        self.api_key = settings.HARMONIC_API_KEY
        if not self.api_key:
            raise ValueError("Missing Harmonic API key: HARMONIC_API_KEY")

        self.session: Optional[aiohttp.ClientSession] = None
        self._session_cm: Any = None
        self.priority = priority
        self.source = source

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

        None covers a not-found, an operational failure and a shed call alike. A caller that
        persists the result should use enrich_company_by_domain_strict, which tells them apart.

        Args:
            domain: Company domain (e.g., "posthog.com")

        Returns:
            Company data dict or None if not found
        """
        domain = self._clean_domain(domain)

        # Try domain variations
        domain_variations = [f"{prefix}{domain}" if prefix else domain for prefix in HARMONIC_DOMAIN_VARIATIONS]

        for domain_variation in domain_variations:
            try:
                variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

                if self.session is None:
                    raise RuntimeError("HTTP session not initialized. Use async context manager.")
                response = await harmonic_request(
                    self.session,
                    "POST",
                    f"{HARMONIC_BASE_URL}/graphql",
                    source=self.source,
                    priority=self.priority,
                    endpoint="/graphql",
                    # Key in a header, not a query param: aiohttp errors carry request_info.real_url,
                    # so a URL-borne key would leak into exception telemetry when a lookup raises.
                    headers={"apikey": self.api_key},
                    json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": variables},
                )
                response.raise_for_status()
                data = await response.json()

                if "errors" in data:
                    continue

                result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                if result.get("companyFound"):
                    company_data = result.get("company")
                    return company_data

            except HarmonicEgressBudgetExhausted:
                # A shed is our own limiter declining to call out, not a Harmonic failure — the
                # limiter already records it as a metric; capturing it here would page on our
                # own throttling working as designed.
                continue
            except Exception as e:
                capture_exception(e)
                continue

        return None

    async def enrich_company_by_domain_strict(self, domain: str) -> HarmonicCompanyLookup:
        """Like enrich_company_by_domain, but distinguishes not-found from operational failure.

        Returns a company-less lookup for a genuine not-found: at least one domain variation
        returned a clean GraphQL response with companyFound false, and no variation found the
        company. A clean not-found is an authoritative Harmonic answer even when the other
        variation errored. Raising in that mixed case let one failing variation exhaust the
        caller's retries and fail the whole lookup with no archive row. In practice that mixed
        case has been rare (a prod trace attributed almost all no-archive-row orgs to DB errors
        before the lookup, not to this path); the point of returning the miss is that every
        terminal outcome now leaves an archived row, and a row is what the recheck, the
        backfill, and the re-enrichment sweep act on. An activity failure feeds none of them.

        Operational failures on EVERY variation (network errors, non-2xx status, JSON decode,
        GraphQL errors) still re-raise, so callers retry and alert instead of mistaking an
        outage for a missing company. On the mixed path — a clean not-found suppressing a
        sibling error — the suppressed error is captured rather than discarded, since that is
        exactly the failure mode that let the original bug hide with no signal anywhere.

        A shed variation always re-raises and is never suppressed by a sibling not-found. A shed
        means Harmonic was never asked, so writing the miss would archive "no Harmonic company"
        over our own throttling, and the sweep would not revisit it for up to 90 days.
        """
        domain = self._clean_domain(domain)
        domain_variations = [f"{prefix}{domain}" if prefix else domain for prefix in HARMONIC_DOMAIN_VARIATIONS]

        last_error: Optional[Exception] = None
        last_error_variation: Optional[str] = None
        shed_error: Optional[HarmonicEgressBudgetExhausted] = None
        saw_clean_not_found = False
        not_found_urn: Optional[str] = None
        for domain_variation in domain_variations:
            try:
                variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

                if self.session is None:
                    raise RuntimeError("HTTP session not initialized. Use async context manager.")
                response = await harmonic_request(
                    self.session,
                    "POST",
                    f"{HARMONIC_BASE_URL}/graphql",
                    source=self.source,
                    priority=self.priority,
                    endpoint="/graphql",
                    # Key in a header, not a query param: aiohttp errors carry request_info.real_url,
                    # so a URL-borne key would leak into exception telemetry when a lookup raises.
                    headers={"apikey": self.api_key},
                    json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": variables},
                )
                response.raise_for_status()
                data = await response.json()

                if "errors" in data:
                    raise RuntimeError(f"Harmonic GraphQL errors for {domain_variation}: {data['errors']}")

                result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                if result.get("companyFound"):
                    return HarmonicCompanyLookup(
                        company=result.get("company"), enrichment_urn=result.get("enrichmentUrn")
                    )
                if result.get("companyFound") is False:
                    saw_clean_not_found = True
                    not_found_urn = not_found_urn or result.get("enrichmentUrn")
            except HarmonicEgressBudgetExhausted as e:
                shed_error = e
                continue
            except Exception as e:
                last_error = e
                last_error_variation = domain_variation
                continue

        if shed_error is not None:
            raise shed_error
        if last_error is not None and not saw_clean_not_found:
            raise last_error
        if last_error is not None:
            capture_exception(last_error, {"domain": domain, "failed_variation": last_error_variation})
        return HarmonicCompanyLookup(company=None, enrichment_urn=not_found_urn)

    async def _enrich_company_by_domain_observing_denial(self, domain: str) -> Optional[dict[str, Any]]:
        """Lookup for the batch path, which must see a denial rather than a miss.

        Delegates to enrich_company_by_domain_strict for its shed-always-wins precedence: a shed on
        one domain variation is never treated as a not-found even when a sibling variation returned
        a clean companyFound=false, because the shed means Harmonic was never asked. enrich_companies_batch
        relies on that to know a domain was denied, not missing, so it can retry it in a later wave.
        """
        lookup = await self.enrich_company_by_domain_strict(domain)
        return lookup.company

    async def get_company_by_urn(self, urn: str) -> Optional[dict[str, Any]]:
        """Resolve a Harmonic company URN (e.g. from relatedCompanies) via the REST profile endpoint.

        Returns None only for a genuine not-found (404). Other failures propagate — like
        enrich_company_by_domain_strict, this does not capture_exception; parent-company
        resolution is optional, so the caller decides whether to swallow the error.
        """
        company_id = urn.rsplit(":", 1)[-1]

        if self.session is None:
            raise RuntimeError("HTTP session not initialized. Use async context manager.")
        # Short cap: a single profile fetch, and it shares the signup activity's 90s budget with
        # the up-to-60s domain lookup — inheriting the session's 30s total would eat all headroom.
        response = await harmonic_request(
            self.session,
            "GET",
            f"{HARMONIC_BASE_URL}/companies/{company_id}",
            source=self.source,
            priority=self.priority,
            endpoint="/companies/{id}",
            headers={"apikey": self.api_key},
            timeout=aiohttp.ClientTimeout(total=10),
        )
        if response.status == 404:
            # Returning without reading the body leaves the connection to the garbage collector,
            # which drops it from the keep-alive pool instead of reusing it.
            response.release()
            return None
        response.raise_for_status()
        return await response.json()

    async def get_enrichment_status(self, urns: list[str]) -> dict[str, dict[str, Any]]:
        """Poll Harmonic's /enrichment_status for a set of tracking URNs, keyed by entity_urn.

        Batches at most 50 URNs per request. Raises on a non-2xx response or a body that
        isn't a list, rather than silently reporting every URN as unqueried.
        """
        if self.session is None:
            raise RuntimeError("HTTP session not initialized. Use async context manager.")

        statuses: dict[str, dict[str, Any]] = {}
        for start in range(0, len(urns), _ENRICHMENT_STATUS_BATCH_SIZE):
            batch = urns[start : start + _ENRICHMENT_STATUS_BATCH_SIZE]
            # Same short cap as get_company_by_urn: this shares the recheck activity's 90s
            # budget with the domain lookup, so it must not inherit the session's 30s total.
            response = await harmonic_request(
                self.session,
                "GET",
                f"{HARMONIC_BASE_URL}/enrichment_status",
                source=self.source,
                priority=self.priority,
                endpoint="/enrichment_status",
                params=[("urns", urn) for urn in batch],
                headers={"apikey": self.api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            response.raise_for_status()
            data = await response.json()

            if not isinstance(data, list):
                raise ValueError(f"unexpected enrichment_status body: {type(data).__name__}")
            for entry in data:
                if isinstance(entry, dict) and isinstance(entry.get("entity_urn"), str):
                    statuses[entry["entity_urn"]] = entry
        return statuses

    async def enrich_companies_batch(self, domains: list[str]) -> list[dict[str, Any] | None]:
        """Enrich multiple domains concurrently, one task per domain.

        An asyncio.Semaphore bounds how many lookups run at once (_ENRICH_MAX_CONCURRENT_LOOKUPS); admission
        for each request is paced individually against the shared egress budget and held at least the
        lane's admission interval after the previous one, serialized through a lock so only the wait
        blocks, not the request itself. A domain shed by the egress limiter
        waits one budget window and retries, up to _ENRICH_MAX_ATTEMPTS. A domain still shed after
        every attempt is reported to error tracking and left None, distinctly from a genuine
        not-found or an operational failure (also None): callers persist these results against a
        Salesforce account, and a shed means Harmonic was never asked.

        Args:
            domains: List of company domains to enrich

        Returns:
            List of company data dicts, same length and order as domains.
        """
        if not domains:
            return []

        results: list[dict[str, Any] | None] = [None] * len(domains)
        semaphore = asyncio.Semaphore(_ENRICH_MAX_CONCURRENT_LOOKUPS)
        pacing_lock = asyncio.Lock()
        next_admission_at = 0.0

        async def wait_for_admission() -> None:
            nonlocal next_admission_at
            async with pacing_lock:
                pace = await asyncio.to_thread(pace_seconds_harmonic, self.priority)
                # The interval keeps admissions inside the lane even while the limiter cannot yet
                # see the calls this batch admitted but has not consumed.
                wait = max(pace, next_admission_at - time.monotonic())
                if wait > 0:
                    await asyncio.sleep(wait)
                next_admission_at = time.monotonic() + admission_interval_harmonic(self.priority)

        async def enrich_one(index: int, domain: str) -> None:
            for attempt in range(1, _ENRICH_MAX_ATTEMPTS + 1):
                async with semaphore:
                    if self.priority is not Priority.CRITICAL:
                        await wait_for_admission()

                    try:
                        results[index] = await self._enrich_company_by_domain_observing_denial(domain)
                        return
                    except HarmonicEgressBudgetExhausted:
                        pass
                    except Exception as e:
                        capture_exception(e, {"domain": domain})
                        return

                if attempt < _ENRICH_MAX_ATTEMPTS:
                    await asyncio.sleep(HARMONIC_WINDOW_SECONDS)

            capture_exception(
                HarmonicEgressBudgetExhausted(
                    f"Harmonic egress budget denied this domain on every attempt ({_ENRICH_MAX_ATTEMPTS})"
                ),
                {"domain": domain},
            )

        await asyncio.gather(*(enrich_one(index, domain) for index, domain in enumerate(domains)))
        return results
