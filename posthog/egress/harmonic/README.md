# Harmonic egress

## Identity

Harmonic meters one account-wide rate limit, and an instance holds a single `HARMONIC_API_KEY`.
Every call draws from one budget under the key `harmonic:account:default`.

## Budget

A single per-second ceiling read from settings at acquire time: `HARMONIC_EGRESS_PER_SECOND_BUDGET` (default 15).
Harmonic documents a limit of 10 requests per second for most endpoints, with a 429 above it.
Search agent and Scout task creation have lower limits of their own, and PostHog calls neither.
The default sits above that on purpose. The `BATCH` reserve floors to 4 of 15 units, so the bulk lane is admitted up to 11 calls a second, next to the documented rate.

## Lanes and callers

The default reserve ladder applies, and it matters here, because the lanes carry very different traffic:

- `CRITICAL`: signup enrichment and the ICP re-enrichment sweep, inside a short Temporal activity budget.
- `BATCH`: the Salesforce enrichment sweep, which yields to them.

The client is `ee/billing/salesforce_enrichment/harmonic_client.py`.
The bulk sweep paces with `pace_seconds_harmonic` and `admission_interval_harmonic` rather than getting denied.
A denied call raises `HarmonicEgressBudgetExhausted`. A caller that folds exceptions into an enrichment miss must catch it first, or a throttled lookup gets recorded as a company Harmonic does not know.

## Rate-limit headers

Harmonic documents `X-Ratelimit-Limit-Second` and `X-Ratelimit-Remaining-Second` on every response, and they feed the `harmonic_api_rate_limit_{limit,remaining}` gauges, with `account` as `resource`.
Production has recorded no value on either gauge, although the recording path sets them for this scope and the worker exports gauges.
Check a live response with the API key before you build a dashboard or tune the budget on them.
Harmonic documents no reset header, so the domain declares no reset gauge.
The counter is `harmonic_api_requests_total`.

## Auth

The caller sends the key in the `apikey` header, never as a URL query parameter, because a URL-borne key leaks into aiohttp exception telemetry.

## Transport

Harmonic is the async domain: it subclasses `AsyncEgressClient`, because its client speaks aiohttp, and the caller supplies its own `aiohttp.ClientSession`.

## Sources

- [API reference, rate limit](https://console.harmonic.ai/docs/api-reference/introduction#rate-limit): the per-second limit, the lower endpoint limits, and the headers. The page renders only with JavaScript, so open it in a browser.
