# logo.dev egress

## Identity

logo.dev meters usage per account, and an instance configures one account.
The whole instance draws from one budget under the key `logodev:account:default`.

## Budget

logo.dev publishes no rate-limit numbers, so the budget is an operator ceiling read from settings at acquire time:

- `LOGODEV_EGRESS_PER_MINUTE_BUDGET` (default 300) smooths bursts, such as a catalog page fanning out cache misses.
- `LOGODEV_EGRESS_HOURLY_BUDGET` (default 5,000) caps total spend.

Icon bytes are never stored server-side, because logo.dev licenses that separately.
Browser caching (`posthog/cdp/services/icons.py` sets `Cache-Control`) is the only dedupe, so steady-state traffic tracks unique (user, icon) first views per day.
Raise the settings if that outgrows the defaults.

## Lanes and callers

The default reserve ladder applies.
The CDP icon picker and MCP store icons (`posthog/cdp/services/icons.py`, source `cdp_icons`) call on the `NORMAL` lane.
Nothing in this domain runs `CRITICAL`, because the icon id is user-controlled and a never-shed lane would make the budget advisory.
A denied call raises `LogoDevEgressBudgetExhausted`, and the caller degrades to no icon.

## Rate-limit headers

logo.dev returns none, so the domain declares no gauges.
The counter is `logodev_api_requests_total`, labeled `account, method, endpoint, status_code, source`.
Image URLs collapse to the `/img/{domain}` endpoint label, so each brand does not mint its own series.

## Auth

- Image CDN requests use `LOGO_DEV_PUBLISHABLE_KEY` (a `pk_` key) as a query parameter.
- Search API requests use `LOGO_DEV_SECRET_KEY` (an `sk_` key) as a bearer token.
- `LOGO_DEV_TOKEN` is a deprecated fallback for image requests only, and never authenticates a Search API request.
