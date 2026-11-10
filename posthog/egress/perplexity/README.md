# Perplexity egress

## Why this is not on the AI gateway

App inference normally goes through the AI gateway (see `.agents/architecture.md`).
Perplexity is an agreed exception: the AI gateway team decided that Perplexity runs outside the gateway, through this domain and with PostHog's own key, and that the gateway can take it over if traffic or spend justifies it.
The decision is in the AI gateway team's Slack channel, thread `p1792783437195869`.
Calls through this domain emit no `$ai_generation` event, so the caller records cost itself from the response's `usage.cost`.

## Identity

Perplexity applies the Agent API request limit to the API organization, shared across every model and every key in it.
An instance holds a single `PERPLEXITY_API_KEY`, so the whole instance draws from one budget under the key `perplexity:account:default`.

## Budget

Perplexity's Agent API limits depend on the usage tier, from 1 request per second at tier 0 up to 33 at tier 4, plus token limits per minute and per hour.
The running process cannot tell which tier its key is on, so the budget is an operator ceiling on spend, read from settings at acquire time:

- `PERPLEXITY_EGRESS_PER_MINUTE_BUDGET` (default 60) stays at the tier 0 request limit.
- `PERPLEXITY_EGRESS_HOURLY_BUDGET` (default 2,000) caps what a runaway caller can spend before anyone notices.

Every Agent API call bills model tokens, and every `web_search` invocation bills $2.50 per 1,000 calls, or $1.00 per 1,000 with `search_type: "fast"`.
Raise the numbers in settings as real traffic grows.

## Lanes and callers

The default reserve ladder applies, and `perplexity_request` defaults to `BATCH`.
The AEO citation runner (`products/aeo/backend/engines.py`, `PerplexityWebSearchEngine`) is the only caller, and it runs on `BATCH`.
It paces with `pace_seconds_perplexity` and `admission_interval_perplexity`, so a full prompt-set run spreads over the window instead of being shed.
A shed call raises `PerplexityEgressBudgetExhausted`, and the engine records it as a failed check.
Nothing in this domain runs `CRITICAL`, because the prompts come from user-managed prompt sets.

## Rate-limit headers

Successful Agent API responses carry `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-used` and `x-ratelimit-reset` (Unix seconds) for the request limit.
The parser reads limit, remaining and reset into the `perplexity_api_rate_limit_{limit,remaining,reset}` gauges, with `agent_requests` as `resource`.
A 429 carries `Retry-After` and none of these headers, and the caller owns the retry.
No response reports the token budget.
The counter is `perplexity_api_requests_total`, labeled `account, method, endpoint, status_code, source`.

## Auth

`PERPLEXITY_API_KEY` authenticates every call as a bearer token.
The caller reads it from settings and passes it to `perplexity_request`.

## Sources

- [Rate limits and usage tiers](https://docs.perplexity.ai/docs/admin/rate-limits-usage-tiers): organization-wide Agent API request and token limits per tier, the `x-ratelimit-*` headers on success, and `Retry-After` without them on a 429.
- [Web search tool](https://docs.perplexity.ai/docs/agent-api/tools/web-search): `search_type`, the `search_results` output item, and the per-invocation price.
- [Agent API models](https://docs.perplexity.ai/docs/agent-api/models): `perplexity/sonar` token prices.
- [Create Agent Response](https://docs.perplexity.ai/api-reference/agent-post): `POST /v1/agent`, bearer auth, and the response `status` and `error` fields.
