# Harmonic egress

## Identity

Harmonic meters one account-wide rate limit, and an instance holds a single `HARMONIC_API_KEY`.
Every call draws from one budget under the key `harmonic:account:default`.

## Budget

A single per-second ceiling read from settings at acquire time: `HARMONIC_EGRESS_PER_SECOND_BUDGET` (default 15).
[#96708](https://github.com/PostHog/posthog/pull/96708) cites Harmonic's API reference for a limit of 10 requests per second on most endpoints, with a 429 above it.
The reference renders only inside Harmonic's console, so this README does not re-check the number.
The default sits above that on purpose. The `BATCH` reserve floors to 4 of 15 units, so the bulk lane is admitted up to 11 calls a second, next to the documented rate.

## Lanes and callers

The default reserve ladder applies, and it matters here, because the lanes carry very different traffic:

- `CRITICAL`: signup enrichment and the ICP re-enrichment sweep, inside a short Temporal activity budget.
- `BATCH`: the Salesforce enrichment sweep, which yields to them.

The client is `ee/billing/salesforce_enrichment/harmonic_client.py`.
The bulk sweep paces with `pace_seconds_harmonic` and `admission_interval_harmonic` rather than getting denied.
A denied call raises `HarmonicEgressBudgetExhausted`. A caller that folds exceptions into an enrichment miss must catch it first, or a throttled lookup gets recorded as a company Harmonic does not know.

## Rate-limit headers

The parser reads `X-Ratelimit-Limit-Second` and `X-Ratelimit-Remaining-Second`, the header names #96708 cites, into the `harmonic_api_rate_limit_{limit,remaining}` gauges, with `account` as `resource`.
Production responses from the endpoints PostHog calls carry neither header, so the gauges stay empty. Do not tune the budget from them.
Harmonic documents no reset header, so the domain declares no reset gauge.
The counter is `harmonic_api_requests_total`.

## Auth

The caller sends the key in the `apikey` header, never as a URL query parameter, because a URL-borne key leaks into aiohttp exception telemetry.

## Transport

Harmonic is the async domain: it subclasses `AsyncEgressClient`, because its client speaks aiohttp, and the caller supplies its own `aiohttp.ClientSession`.
