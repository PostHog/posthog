# Vercel egress

Calls to the Vercel REST API (`api.vercel.com`) that the Vercel Marketplace integration makes for an installation: resource imports, secrets, feature flag and experiment items, account lookups, OAuth and SSO token exchanges, and the billing service's calls through the Vercel proxy.

## Identity

The Vercel installation id (`icfg_...`), recorded as the `installation` label.
Vercel issues one access token per installation, and several PostHog teams in one organization share that installation.
A call made before PostHog knows the installation, such as an OAuth code exchange or an SSO token exchange, records no installation.

## Budget

None: calls are recorded, never gated (`RecordedEgressClient`).
Vercel publishes a limit for each endpoint, counted per user, and a different one for each endpoint: 10 requests a minute for an invoice submission, 100 for a resource import, 240 for a secrets update.
One budget per installation cannot model limits that differ by endpoint.
Vercel publishes no limit for experimentation items, which a bulk feature flag sync sends one per flag.
A budget would stop a large team's sync part way through and leave Vercel with only some of its flags.
Size a budget from `vercel_api_requests_total` once it has production traffic, and decide what a caller does when it is denied.

## Lanes and callers

No lanes, because nothing is gated.

- `ee/vercel/client.py` (`VercelAPIClient`), source `integration`: feature flag and experiment sync, resource imports and secrets, installation and account lookups, and the OAuth and SSO token exchanges.
- `ee/vercel/client.py` (`get_installation_access_token`), source `installation_token`: the short-lived installation token requests (`client_credentials` on `/v2/oauth/access_token`). Workers that miss the token cache together wait on a lock per installation, so one of them sends the request.
- `ee/api/vercel/vercel_proxy.py`, source `billing_proxy`: the billing service's invoice and usage calls.

## Rate-limit headers

None documented, so the domain declares no gauges.
Vercel reports a rate limit in the error body of the response instead.
The counter is `vercel_api_requests_total`, labeled `installation, method, endpoint, status_code, source`.
The endpoint label replaces the segment after `installations`, `resources`, `items` and `invoices` with `{id}`, because an item id is a feature flag key.
The billing proxy passes its own label, because the billing service chooses the path after `/billing/invoices/`.

## Auth

The caller sends the installation's access token as a bearer token, through the `VercelAPIClient` session or its own headers.
The caller requests that token for each installation with the integration's client id and secret, and the token exchanges send the same client credentials.

## Sources

- [Rate limits](https://vercel.com/docs/limits/rate-limits): limits per endpoint for each minute, scoped per user, for example `api-marketplace-submit-invoice` (10), `api-integrations-import-resource` (100) and `api-integrations-update-resource-secrets` (240). No row covers experimentation items or `/v2/oauth/access_token`. The page names no rate-limit response header.
- [Errors](https://vercel.com/docs/rest-api/errors): a rate-limited response carries `rate_limited` and a `limit` object (`remaining`, `reset`, `resetMs`, `total`) in its JSON body, and the limit applies to each endpoint separately. Unverified: the page does not document a `Retry-After` header.
