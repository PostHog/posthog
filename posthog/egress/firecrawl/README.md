# Firecrawl egress

## Identity

Firecrawl meters per account, and an instance holds a single API key.
The whole instance draws from one budget under the key `firecrawl:account:default`.

## Budget

Firecrawl's per-plan limits are not discoverable from the running process, so the budget is an operator ceiling on spend, read from settings at acquire time:

- `FIRECRAWL_EGRESS_PER_MINUTE_BUDGET` (default 60) smooths a burst of concurrent callers.
- `FIRECRAWL_EGRESS_HOURLY_BUDGET` (default 1,000) caps what a runaway caller can spend before anyone notices.

One scrape costs one credit, and one search costs two credits per ten results, so these numbers cap a bill as much as a rate.
`search` reserves a second budget unit before the transport reserves its own, so one search draws two units.
They are sized for roughly one scrape per event a person triggers, and are meant to be raised in settings as that grows.

## Lanes and callers

The default reserve ladder applies, and `firecrawl_request` defaults to `NORMAL`.
Domain research for Tasks (`products/tasks/backend/facade/domain_research.py`) scrapes on `NORMAL`.
The AI-enrichment label tools (`products/growth/backend/enrichment/tools.py`) search and scrape on `BATCH`.
Nothing in this domain runs `CRITICAL`, because what gets scraped comes from user-supplied input and callers can do without the scrape.

## Rate-limit headers

When a response carries `X-RateLimit-Remaining` and `X-RateLimit-Limit`, they feed the `firecrawl_api_rate_limit_{remaining,limit}` gauges, with the endpoint path as `resource`, because Firecrawl meters each endpoint separately.
The reset header is not recorded, because Firecrawl does not document whether it is an epoch or a number of seconds.
The counter is `firecrawl_api_requests_total`.

## Auth

`FIRECRAWL_API_KEY` authenticates every call as a bearer token.
An instance without one makes no request at all: `scrape` and `search` raise `FirecrawlNotConfigured`.

## Typed client

Callers use `client.py` rather than `firecrawl_request`.
`scrape(url, source=...)` returns a `FirecrawlScrape` (markdown, summary, page title, description, status code, credits used).
It raises `FirecrawlScrapeFailed` when Firecrawl answers with anything but a successful scrape, including a 200 that carries `success: false`.
`search(query, source=...)` returns a `FirecrawlSearch` of web results and raises `FirecrawlSearchFailed` on the same conditions.
It rejects a `limit` above `MAX_SEARCH_LIMIT` or a query above `MAX_SEARCH_QUERY_CHARS` before any call.
Only `POST /v2/scrape` and `POST /v2/search` are wired up.
