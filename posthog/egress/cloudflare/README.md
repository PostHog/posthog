# Cloudflare egress

## Identity

Cloudflare limits API calls per user or token, and meters cache purges per account.
An instance holds one purge token, so the whole instance draws from one budget under the key `cloudflare:account:default`.

## Budget

Cloudflare allows 1,200 API requests per five minutes per token, and blocks every call from that token for the next five minutes after a 429.
Single-file purges have their own per-account limit of at least 800 URLs per second, depending on the plan.
The budget is an operator ceiling far below both, read from settings at acquire time:

- `CLOUDFLARE_EGRESS_PER_MINUTE_BUDGET` (default 30).
- `CLOUDFLARE_EGRESS_HOURLY_BUDGET` (default 300).

The ceilings exist so that a runaway caller cannot lock the token out of the API.

## Lanes and callers

The default reserve ladder applies, and `cloudflare_request` defaults to `NORMAL`.
The uploaded media admin (`posthog/admin/admins/uploaded_media_admin.py`) purges an image's public URLs on `NORMAL` when staff stop serving it or delete its stored file.

## Rate-limit headers

Cloudflare documents `Ratelimit` and `Ratelimit-Policy` headers, and `retry-after` once the limit is exceeded.
The callers make a few requests a day at most, so the domain parses none of them and declares no gauges.
The counter is `cloudflare_api_requests_total`, labeled `account, method, endpoint, status_code, source`.
`endpoint` is the path template, so the zone id never becomes a label.

## Auth

Every call sends an API token as a bearer token.
The token needs the `Cache Purge` permission on the zone.
The caller owns where the token comes from: uploaded media reads `UPLOADED_MEDIA_CDN_PURGE_TOKEN`.

## Typed client

`purge_urls(urls, zone_id=..., api_token=..., source=...)` calls `POST /zones/{zone_id}/purge_cache` with a `files` list.
It sends at most 100 URLs per request, the limit on every plan below Enterprise.
It raises `CloudflarePurgeFailed` when Cloudflare answers with an HTTP error or `success: false`.
A 200 with `success: true` means Cloudflare accepted the purge, not that every edge already dropped its copy.

## Sources

- [API rate limits](https://developers.cloudflare.com/fundamentals/api/reference/limits/): 1,200 requests per five minutes per user or token, the five-minute block after a 429, and the `Ratelimit`, `Ratelimit-Policy` and `retry-after` headers.
- [Purge cache limits](https://developers.cloudflare.com/cache/how-to/purge-cache/): single-file purge limits per account by plan, and at most 100 URLs per request below Enterprise.
- [Purge cached content API](https://developers.cloudflare.com/api/resources/cache/methods/purge/): the endpoint, bearer auth, the `Cache Purge` permission, the `files` body, and the `success` and `errors` response fields.
