import asyncio
from typing import Any, Optional

from django.conf import settings

import aiohttp

from posthog.dataclasses import frozen
from posthog.egress.harmonic.limiter import pace_seconds_harmonic
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

# enrich_companies_batch fires this many lookups concurrently per wave, re-pacing before each one,
# so a wave that lands after the budget has been drawn down actually waits instead of bursting.
_ENRICH_WAVE_SIZE = 10

# Bounds how many times enrich_companies_batch retries a domain the egress limiter sheds, so a
# sustained budget crunch degrades to a bounded number of misses within one call rather than
# retrying forever.
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

        None on every variation is a catch-all: it means not-found, a network or API error, or
        the egress limiter shedding the call, with no way to tell those apart from the return
        value alone. That is fine for a caller that just skips the domain and retries later, but
        wrong for a caller that would persist a
        not-found as data — use enrich_company_by_domain_strict there instead, which raises on an
        operational failure or a shed rather than folding it into the same result as a real miss.

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

        A shed variation (the egress limiter denying the call) is never eligible for that
        suppression, even when a sibling variation came back a clean not-found: unlike a network
        error, a shed means Harmonic was never asked, so a sibling's not-found is not evidence
        about it. Swallowing a shed into a not-found would write an "org has no Harmonic company"
        result the re-enrichment sweep would not revisit for up to 90 days, purely because our
        own budget was tight when this call landed — always re-raise it instead.
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
        """Batch-path lookup that lets a HarmonicEgressBudgetExhausted denial propagate instead of
        folding it into the same None enrich_company_by_domain returns for a genuine miss.

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
        """Enrich multiple domains concurrently, in waves paced against the shared egress budget.

        Pacing is recomputed before each wave rather than once for the whole batch: pace_seconds
        reads live limiter state, so only a wave that actually finds the budget consumed waits.
        Pacing once up front and then gathering the whole batch would let a later wave burst past
        the budget the instant an earlier wave (or unrelated traffic) had drawn it down, the same
        defect as not pacing at all, just delayed.

        A domain the limiter sheds mid-wave is not a miss: enrich_company_by_domain would fold that
        denial into the same None a genuine not-found returns, and callers that persist results
        (e.g. as a Salesforce account update) cannot tell the two apart. So a shed domain is retried
        in a later wave, up to _ENRICH_MAX_ATTEMPTS, instead of being recorded immediately.

        Args:
            domains: List of company domains to enrich

        Returns:
            List of company data dicts, same length and order as domains. A slot is None for a
            genuine not-found or an operational failure, and also for a domain still shed after
            every attempt: that last case is reported to error tracking first, since it must not
            look like a genuine miss on inspection there even though the return value can't carry
            the distinction (callers zip this list against the input domains).
        """
        if not domains:
            return []

        results: list[dict[str, Any] | None] = [None] * len(domains)
        pending = list(range(len(domains)))

        for _attempt in range(_ENRICH_MAX_ATTEMPTS):
            if not pending:
                break

            denied: list[int] = []
            for wave_start in range(0, len(pending), _ENRICH_WAVE_SIZE):
                wave = pending[wave_start : wave_start + _ENRICH_WAVE_SIZE]

                # CRITICAL is never shed by the transport (_raise_if_denied never raises on it), so
                # pacing it would only add latency to an interactive caller for no admission benefit.
                if self.priority is not Priority.CRITICAL:
                    pace = pace_seconds_harmonic(self.priority)
                    if pace > 0:
                        await asyncio.sleep(pace)

                wave_results: list[dict[str, Any] | BaseException | None] = await asyncio.gather(
                    *(self._enrich_company_by_domain_observing_denial(domains[i]) for i in wave),
                    return_exceptions=True,
                )

                for index, result in zip(wave, wave_results):
                    if isinstance(result, HarmonicEgressBudgetExhausted):
                        denied.append(index)
                    elif isinstance(result, BaseException):
                        capture_exception(result)
                    else:
                        results[index] = result

            pending = denied

        for index in pending:
            capture_exception(
                HarmonicEgressBudgetExhausted(
                    f"Harmonic egress budget denied this domain on every attempt ({_ENRICH_MAX_ATTEMPTS})"
                ),
                {"domain": domains[index]},
            )

        return results
