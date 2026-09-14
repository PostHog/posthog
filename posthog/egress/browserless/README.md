# Browserless egress

## Identity

The **fleet**: a hash of host and token together, under the key `browserless:fleet:<hash>`.
Either alone is wrong.
The same credential against a different host is a different set of workers, and a self-hosted fleet often carries no token, which would collapse every such deployment onto one budget if the token were the whole identity.
The fleet is also what actually runs out: two callers pointed at one Browserless draw from one pool of workers whatever product they serve, so a narrower key would let each stay inside its own limit and still exhaust the fleet between them.
The hash keeps the token out of the metric label.

## Budget

Browserless meters **concurrent sessions**, not requests, and a session is held for the whole page load: a few seconds for a screenshot, tens of seconds for a Lighthouse audit.
So the budget counts browser loads asked of one fleet, and the ceilings are small next to an API budget:

- `BROWSERLESS_EGRESS_PER_MINUTE_BUDGET` (default 120)
- `BROWSERLESS_EGRESS_HOURLY_BUDGET` (default 2,000)

## Lanes and callers

The default reserve ladder applies, because callers differ sharply in urgency.
Heatmap screenshots (`products/web_analytics/backend/tasks/heatmap_screenshot.py`) run `NORMAL`, because somebody is watching a spinner.
A background consumer should run `BATCH`, so that it is shed first and leaves headroom for the render a person is waiting on.
A denied call raises `BrowserlessEgressBudgetExhausted`; the heatmap caller maps it to its existing retryable error, under its own failure cause, so a busy fleet is not read as a broken one.

## Rate-limit headers

Browserless publishes none.
Its `X-Response-*` headers describe the page it fetched, not the API's budget, so the domain declares no gauges.
The counter is `browserless_requests_total`, labeled `scope, method, endpoint, status_code, source`.

## Auth

The token stays in the URL's query string, because Browserless REST routes do not accept an `Authorization` header.
`browserless_request` also takes the token separately, so the fleet can be fingerprinted without parsing the URL.
