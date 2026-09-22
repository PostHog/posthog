# GitHub egress

GitHub is the reference domain.
Every GitHub API call in the codebase goes through it.

## Identity

The GitHub App **installation id**, because GitHub meters the rate limit per installation.
Several PostHog integration rows can share one installation, and they all draw on its one budget.
The limiter keys are `github:installation:<id>`, `github_search:installation:<id>`, and `github_code_search:installation:<id>`.

## Budget

GitHub meters its REST resources on separate per-installation counters, so this domain registers three limiter domains, and the transport routes each request to its meter by URL:

- `github`: the `core` resource (5,000–15,000/hour), scaled to the installation's real tier. `api_request` persists each installation's last-observed core `X-RateLimit-Limit` (only trusted installation-token responses feed this), and the policy budgets 90% of it for the hour with a proportional per-minute smoothing cap. Unobserved installations fall back to `GITHUB_EGRESS_HOURLY_BUDGET` (13,500) and `GITHUB_EGRESS_PER_MINUTE_BUDGET` (750) until their first recorded response. Both settings are ceilings that tier scaling can only lower.
- `github_search`: the `search` resource, a static 27/minute under GitHub's real 30/minute.
- `github_code_search`: the `code_search` resource (`/search/code`), a static 8/minute under GitHub's real 10/minute.

The two search budgets are static because GitHub's search limits do not depend on the plan tier, so there is no tier to observe.
GraphQL routes to `core`. GitHub meters GraphQL by points, which a request counter cannot model, so charging it to `core` errs conservative.

## Lanes and callers

All three budgets use the default reserve ladder.
Deferrable background callers construct their client on the `BATCH` lane (`GitHubIntegration(integration, source=..., priority=Priority.BATCH)`; `api_request` also takes a per-call override).
A shed sweep stops for the cycle and resumes on the next scheduled run.
A caller that walks pages, such as the warehouse source, paces with `github_installation_pace_seconds` instead of getting denied.
The warehouse source's page fetches run on `BATCH`, while its repository validation and webhook management run on `NORMAL`, because a person waits on them. Customer Analytics feature-request link and resume lookups also run on `NORMAL` because an editor waits for the current issue state.

The `BATCH` floor on the `core` resource is **demand-responsive**, because a reserve is only worth holding against traffic that exists.
An installation whose only consumer is a bulk one (a warehouse backfill of a repository nothing else touches) would otherwise forfeit 30% of its hourly budget to contention that never arrives, and the hourly budget is what decides whether a large backfill finishes in one run.
So a non-`BATCH` `core` call writes a short-lived per-installation marker (`note_interactive_demand`), and the policy holds the full 70% floor only while that marker is present; without it `BATCH` falls back to a 10% floor, the same floor `NORMAL` keeps.
Three details make that safe: the marker is written on the attempt rather than the outcome, so a _denied_ interactive call still counts; the floor matches `NORMAL`'s rather than dropping toward zero, so an unopposed backfill can never saturate the window past the point where the first interactive call would itself be denied, regardless of the marker it just wrote; and an unreachable cache reports demand as present, so a cache outage cannot hand the whole budget to bulk traffic.
The two search resources keep the flat default ladder, because they are metered on their own counters and core demand says nothing about them.

## Rate-limit headers

`X-RateLimit-Remaining`, `X-RateLimit-Limit`, `X-RateLimit-Reset` and `X-RateLimit-Resource` feed the `github_integration_api_rate_limit_{remaining,limit,reset_timestamp_seconds}` gauges, labeled `installation_id, resource`.
The counter is `github_integration_api_requests_total`, labeled `installation_id, method, endpoint, status_code, source`.
Endpoint labels template out owner/repo, numeric ids, commit SHAs, and free-form tails (file paths, compare refs), so `/repos/{owner}/{repo}/statuses/{sha}` stays one series.

## Auth

`github_request` is token-agnostic (installation token, user token, PAT, or PostHog's shared token) and stateless:

```python
from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority

resp = github_request(
    "GET",
    url,
    source="visual_review",
    headers={"Authorization": f"Bearer {token}"},  # caller owns auth; the client adds Accept + API version
    installation_id=installation_id,               # budget owner; None = identity-blind (records volume only)
    priority=Priority.CRITICAL,                     # CRITICAL never blocks; sheddable lanes raise on denial
)
```

`raise_if_github_rate_limited` and `GitHubRateLimitError` (GitHub's own 429, the reactive twin of `GitHubEgressBudgetExhausted`) live in `transport.py` for callers that want to raise and retry.
The model-coupled `GitHubIntegrationBase.api_request` layers the installation-token lifecycle (proactive refresh, 401 refresh-retry, rate-limit raising, per-instance `source` attribution) on top. Hold an integration, call that. Hold a bare token, call `github_request`.
The `github-api-calls-go-through-egress` semgrep rule reads the URL argument only, so a call that builds its URL into a variable first gets past it, and review is the only check on that shape.

## Identity-blind callers and the PAT scope decision

Some callers have no installation in scope.
The important one is a warehouse source authenticated with a **personal access token (PAT)**: a customer's own token on the customer's own budget, disconnected from any PostHog installation (error tracking's public-repo path is the other).
These record the counter only, under an empty `installation_id`, and skip both the limiter and the gauges.
The counter still sums correctly, but identity-blind callers are **not distinguishable from one another**: every PAT lands on the same empty series, and writing headroom to a shared empty gauge would let unrelated tokens clobber each other.

The scope line:

- PAT request-**volume** telemetry is in scope and shipped (aggregate only).
- PAT rate-limit **headroom** and PAT **limiting** are deferred, to revisit.

Both need the same missing piece: a per-token identity (a hash of the token) to key on.
The headers are already on the response, so it needs no request restructuring, but a token-hash label is higher-cardinality than an installation, so it's a deliberate choice, not a default.
`GithubEgressIdentity` is the seam where such a key would thread through.

## Caveats

The cache-hit counter in `github_integration_base` is a separate concern (which rows are reading a warm cache) and legitimately keys by the integration row, not by the installation. It is not egress-budget telemetry.
The caches it counts are installation-scoped, so a row can record a hit on an entry another row on the same installation filled.

## Sources

- [Rate limits for the REST API](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api): installation limits and the `x-ratelimit-*` headers.
- [Search](https://docs.github.com/en/rest/search/search): the search and code search limits per minute.
