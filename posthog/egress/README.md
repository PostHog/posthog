# Outbound egress: rate limiting, observability, transport

General-purpose controls for the calls PostHog makes _out_ to third-party APIs.
GitHub was the first consumer and logo.dev (`logodev/`) is the second, but the package is built for more.
A new outbound integration that needs rate-limiting or egress telemetry belongs here as a `<domain>/` incarnation (see [Adding a new egress domain](#adding-a-new-egress-domain)), never hand-rolled around `requests`.
Three lanes, one per subpackage:

- **`limiter/`** — shared, Redis-backed budgets so every worker process draws from one limit and PostHog stays inside an external API's rate limit, with priority lanes so bulk traffic can't starve critical traffic.
- **`observability/`** — the metrics analog: request volume plus the API's own rate-limit headers, on one Prometheus metric set.
- **`transport/`** — the HTTP client that composes the other two: one request that is gated _and_ recorded by construction, so no caller can bypass either.

This is _outbound_ egress — what PostHog sends.
It is unrelated to `posthog.rate_limit`, which throttles _inbound_ DRF requests from clients.

All three lanes are **domain-generic** and domain-free; each third-party API is an incarnation under its own subpackage (`github/`, `logodev/`, `firecrawl/`), supplying a budget policy, a metric set + parser, and a transport subclass.
Adding a new outbound API is another `<domain>/` folder, not a change to the mechanisms.

## Rate limiting

### Using it

A consumer identifies a budget with a limiter key shaped `{domain}:{scope}:{id}` — e.g. `github:installation:123`.
Go through the facade, never the backing library:

```python
from posthog.egress.limiter.policies import Priority
from posthog.egress.github.limiter import consume_github_installation_sync

if not consume_github_installation_sync(installation_id, priority=Priority.BATCH, source="warehouse"):
    # Budget exhausted — back off and retry, defer, or drop. The limiter never blocks or sleeps.
    raise SomeRetryableError(...)
```

`acquire` (async) and `consume_sync` (sync, for callers outside an event loop) both return `True` if the call fits the shared budget and `False` if it would exceed it.
They are **non-blocking** — the caller decides what to do on `False`.
The GitHub helpers wrap the key construction; other domains expose their own thin gate the same way.

### Pacing (for callers that can wait)

Getting denied is recoverable but wasteful: the caller learns nothing about _when_ the budget frees, so it backs off blind, and the budget it already spent stays spent.
A caller that can wait — a bulk import walking pages, not a request serving a person — should instead ask how long to wait and not get denied at all:

```python
pace = get_outbound_rate_limiter().pace_seconds(key, priority=Priority.BATCH)
if pace > 0:
    ...  # the caller owns the wait; the limiter never sleeps
```

`pace_seconds` returns **0 while a window still holds more than half of that priority's allowance**, so a short run is never slowed for a budget it cannot dent.
Below that it spreads the allowance that is left over the time left in the window, which is the interval that keeps the caller admitted instead of shed.
It reads the same reserved floors admission does, so a `BATCH` caller paces off the share it may actually take, not the whole window.

Two things it is not.
It is **advisory** — `acquire`/`consume_sync` remain the only authority on whether a call is admitted, so a bug here cannot over-admit.
And it is not a wait-for-reset: these are sliding windows, which free continuously, so waiting for a reset would idle for a whole window to get budget that was arriving all along.
A store failure answers 0 rather than raising, because pacing sits in front of every gated call and the in-memory fallback's headroom is one process's, not the shared budget's.

### Budgets (policies)

A budget is a `RatePolicy`: one or more `(count, period_seconds)` limits enforced _together_, so you can cap the hour and smooth per-minute bursts on the same key.
Each domain registers its policy with `register_policy(domain, policy)`, usually as a provider taking the full limiter key, so the budget is read at acquire time (settings + per-scope state) rather than frozen at import.
GitHub meters its REST resources on **separate per-installation counters**, so it registers three domains — one per resource — and the transport routes each request to its meter by URL:

- `github` — the `core` resource (5,000–15,000/hour), budgeted per **installation** and scaled to the installation's real tier: `api_request` persists each installation's last-observed core `X-RateLimit-Limit` (only trusted installation-token responses feed this), and the policy budgets 90% of it for the hour with a proportional per-minute smoothing cap (most installations sit on GitHub's 5,000/hour tier, not the 15,000 top tier). Unobserved installations fall back to the settings defaults (13,500/hour + 750/minute) until their first recorded response.
- `github_search` — the `search` resource, a static 27/minute (under GitHub's real 30/min).
- `github_code_search` — the `code_search` resource (`/search/code`), a static 8/minute (under GitHub's real 10/min).

The two search budgets are static because GitHub's search rate limits are fixed regardless of the account's plan tier, so there is no tier to observe (unlike core).
Budgets stay deliberately under the real ceiling so reactive backoff absorbs drift (clock skew, multi-process races, untracked PAT traffic on the same account).

logo.dev (`logodev/`) meters per account, so a single `logodev` domain carries one instance-wide budget under a constant scope.
Image CDN requests use `LOGO_DEV_PUBLISHABLE_KEY` (a `pk_` key) as a query parameter, while Search API requests use `LOGO_DEV_SECRET_KEY` (an `sk_` key) as a bearer token.
`LOGO_DEV_TOKEN` is a deprecated compatibility fallback for image requests only and is never used to authenticate Search API requests.
logo.dev publishes no rate-limit numbers, so the budgets are static operator ceilings read from settings at acquire time: `LOGODEV_EGRESS_PER_MINUTE_BUDGET` (default 300) smooths bursts and `LOGODEV_EGRESS_HOURLY_BUDGET` (default 5,000) caps total spend.
Every logo.dev call runs on a sheddable lane — the icon id is user-controlled, so nothing in this domain runs `CRITICAL`.
Icon bytes are never stored server-side (logo.dev licenses that separately), so steady-state traffic is deduped only by browser caching (`posthog/cdp/services/icons.py` sets `Cache-Control`) and tracks unique (user, icon) first views per day — raise the settings if that outgrows the defaults.

Firecrawl (`firecrawl/`) meters per account and bills a credit per call, and an instance holds a single API key, so it follows the same shape: one `firecrawl` domain, one instance-wide budget under a constant scope.
Firecrawl's per-plan limits are not discoverable from the running process, so the budgets are operator ceilings on spend read from settings at acquire time: `FIRECRAWL_EGRESS_PER_MINUTE_BUDGET` (default 60) smooths a burst of concurrent callers, and `FIRECRAWL_EGRESS_HOURLY_BUDGET` (default 1,000) caps what a runaway caller can spend before anyone notices.
One scrape is one credit, so those numbers cap a bill as much as a rate; they are sized for traffic of roughly one scrape per event a person triggers, and are meant to be raised in settings as that grows.
Every Firecrawl call runs on a sheddable lane: what gets scraped is derived from user-supplied input and callers can do without the scrape, so nothing in this domain runs `CRITICAL`.
`FIRECRAWL_API_KEY` authenticates every call as a bearer token; an instance without one makes no request at all (`FirecrawlNotConfigured`).

### Priority lanes

Priority (`CRITICAL` / `NORMAL` / `BATCH`) controls how sheddable a call is when the budget gets tight.
All priorities draw from the _same_ per-key counter — the lane only changes how much headroom must stay free for the call to be admitted (a _reserved floor_), so deferrable bulk traffic (`BATCH`) is denied before critical traffic as the budget fills, without ever splitting the budget into separate buckets.
Admission tests `n + reserve` but only consumes `n`, so an empty reserve is bit-identical to pre-priority behavior.
GitHub's reserve ladder is active: `BATCH` calls are denied once 70% of a window is consumed and `NORMAL` at 90%, while `CRITICAL` may use the full budget.
Deferrable background callers construct their client on the `BATCH` lane (`GitHubIntegration(integration, source=..., priority=Priority.BATCH)`; `api_request` also takes a per-call override) — a shed sweep stops for the cycle and resumes on the next scheduled run.

The `BATCH` floor on the `core` resource is **demand-responsive**, because a reserve is only worth holding against traffic that exists.
An installation whose only consumer is a bulk one — a warehouse backfill of a repository nothing else touches — would otherwise forfeit 30% of its hourly budget to contention that never arrives, and the hourly budget is what decides whether a large backfill finishes in one run.
So a non-`BATCH` `core` call writes a short-lived per-installation marker (`note_interactive_demand`), and the policy holds the full 70% floor only while that marker is present; without it `BATCH` falls back to a 10% floor — the same floor `NORMAL` keeps.
Three details make that safe: the marker is written on the attempt rather than the outcome, so a _denied_ interactive call still counts; the floor matches `NORMAL`'s rather than dropping toward zero, so an unopposed backfill can never saturate the window past the point where the first interactive call would itself be denied, regardless of the marker it just wrote; and an unreachable cache reports demand as present, so a cache outage cannot hand the whole budget to bulk traffic.
The two search resources keep the flat ladder — they are metered on their own counters, so core demand says nothing about them.

### Backend

A sliding-window counter over Redis holds the shared budget across worker processes — O(1) memory per key, self-expiring, no background grooming.
When Redis is unavailable it degrades to a per-process in-memory counter, shrunk by `in_memory_divider` so N processes don't together allow N× the shared limit.
That fallback is best-effort: **the consumer's reactive backoff (e.g. honoring a 429) is the real backstop**, and the limiter is a proactive smoother on top.
All library and Redis specifics live in the backend module, so the facade and consumers stay backend-agnostic and the algorithm stays swappable.

## Egress observability

Record every response through the domain's recorder (e.g. `record_github_api_response`) so request volume and the API's rate-limit headers land on one metric set, whichever subsystem made the call.

- **Counter** (`github_integration_api_requests_total`) — request volume, always recorded, including errors, rate-limited responses, and transport exceptions that raise before a response. Labeled `installation_id, method, endpoint, status_code, source`.
- **Gauges** (`github_integration_api_rate_limit_{remaining,limit,reset_timestamp_seconds}`) — last-observed budget headroom parsed from the API's response headers (GitHub: `X-RateLimit-*`). Labeled `installation_id, resource`, with no `source`, because the budget is shared across sources.

The `source` label (e.g. `integration`, `visual_review`, `warehouse`) carries per-subsystem attribution.
Endpoint labels are normalized to bound cardinality: owner/repo, numeric ids, commit SHAs, and free-form tails (file paths, compare refs) are templated out (`/repos/{owner}/{repo}/statuses/{sha}`), so raw-URL callers don't mint one label per commit.

## Transport

`github_request` is the one way to call GitHub from anywhere — it gates on the shared per-installation budget and records telemetry by construction, so a caller physically can't forget either:

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

It's **token-agnostic** (installation token, user token, PAT, or PostHog's shared token) and stateless.
The generic `EgressClient` base owns the gate → request → record algorithm and the priority-based denial semantics (CRITICAL proceeds even when the budget is spent — GitHub's own 429 is the backstop; sheddable lanes raise `EgressBudgetExhausted`); `GitHubClient` fills the domain hooks.
Response handling — what to do on a 403/429 — stays with the caller: `raise_if_github_rate_limited` / `GitHubRateLimitError` (GitHub's own 429, the reactive twin of our `EgressBudgetExhausted`) live in `github/transport.py` for callers that want to raise-and-retry.
The model-coupled `GitHubIntegrationBase.api_request` layers the installation-token lifecycle (proactive refresh, 401 refresh-retry, rate-limit raising, per-instance `source` attribution) on top — hold an integration, call that; hold a bare token, call `github_request`.
Raw `requests` calls against `api.github.com` are blocked by the `github-api-calls-go-through-egress` semgrep rule (`.semgrep/devex-rules/`), so new callers land on one of these two paths by construction.

Firecrawl callers go through `firecrawl/client.py` rather than `firecrawl_request` directly: `scrape(url, source=...)` returns a typed `FirecrawlScrape` (markdown, summary, plus the page title, description, status code and credits used) and raises `FirecrawlScrapeFailed` when Firecrawl answers with anything but a successful scrape, including the 200 responses that carry `success: false`.
Only `POST /v2/scrape` is wired up, and the client reads `FIRECRAWL_API_KEY` from settings so the transport stays token-agnostic like the others.

Slack Web API calls use `SlackWebClient` (and `SlackAsyncWebClient` where needed) from `slack/` so
request volume, method, status, source, and workspace are recorded consistently. Slack applies Web API
limits per method, workspace, and app, with additional special limits such as per-channel message
posting. Installation age and Marketplace status can also change the limits for history methods.
Slack does not return remaining-budget headers, so Slack egress records each HTTP attempt and the
app-and-method-specific `Retry-After` from 429 responses. It does not proactively limit requests.
Callers continue to own reactive retries.

Incoming webhooks and interactivity `response_url` calls are not Slack Web API calls. Their secret URL is
the budget identity, and persisting or labeling by it would expose credentials. Keep their error handling
with the caller rather than assigning them to a shared workspace bucket.

## The one identity rule

Everything keys on the **budget owner in the external API's own id space** — for GitHub the App **installation id**, because that is what GitHub meters.
It is **never** a PostHog DB row id (`Integration.id`).
Several PostHog integration rows can point at the same installation (multiple projects, one org), and GitHub gives that installation one shared budget: key a gauge by the row and one real budget splits into N flip-flopping series; key by the installation and you get one true series.
Per-caller attribution is the `source` label's job, not the identity's.

> The cache-hit counter in `github_integration_base` is a separate concern (cache efficiency per connection) and legitimately keys by the integration row — it is not egress-budget telemetry.

## Identity-blind callers and the PAT scope decision

Some callers have no installation in scope.
The important one is a warehouse source authenticated with a **personal access token (PAT)**: a customer's own token on the customer's own budget, disconnected from any PostHog installation (error tracking's public-repo path is the other).
These record the counter only, under an empty `installation_id`, and skip both the limiter and the gauges.
The counter still sums correctly, but identity-blind callers are **not distinguishable from one another** — every PAT lands on the same empty series, and writing headroom to a shared empty gauge would let unrelated tokens clobber each other.

Scope line, as of the telemetry unification:

- PAT request-**volume** telemetry is in scope and shipped (aggregate only).
- PAT rate-limit **headroom** and PAT **limiting** are deferred — revisit.

Both need the same missing piece: a per-token identity (a hash of the token) to key on.
The headers are already on the response, so it needs no request restructuring — but a token-hash label is higher-cardinality than an installation, so it's a deliberate choice, not a default.
`GithubEgressIdentity` is the seam where such a key would thread through.

## Adding a new egress domain

Add a `<domain>/` subpackage with three small adapters (see `github/`, or `firecrawl/` for a smaller one):

- `limiter.py` — register a budget with `register_policy("<domain>", provider)` and a thin gate that builds the `{domain}:{scope}:{id}` key.
- `observability.py` — an observability adapter (metric set, response parser, endpoint normalizer) and the recorders.
- `transport.py` — an `EgressClient` subclass filling the domain hooks (headers, gate, recorders, normalizer, budget-exhausted error), exposed as a `<domain>_request` helper.

A domain whose callers all hit the same few endpoints can add a fourth module, a typed client over the transport (see `firecrawl/client.py`), so call sites don't hand-build request bodies or re-parse the same response shape.

Keep the identity in the external API's id space, keep the subpackage free of `posthog.models` imports, and remember the limiter is non-blocking — the caller owns the back-off.
