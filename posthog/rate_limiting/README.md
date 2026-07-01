# Outbound rate limiting & egress observability

General-purpose controls for the calls PostHog makes _out_ to third-party APIs.
GitHub is the first consumer, but the package is built for more.
There are two independent halves:

- **Rate limiting** — shared, Redis-backed budgets so every worker process draws from one limit and PostHog stays inside an external API's rate limit, with priority lanes so bulk traffic can't starve critical traffic.
- **Egress observability** — the metrics analog: request volume plus the API's own rate-limit headers, on one Prometheus metric set.

This is _outbound_ limiting — what PostHog sends.
It is unrelated to `posthog.rate_limit`, which throttles _inbound_ DRF requests from clients.

Both halves are **domain-generic**: a mechanism plus a small per-domain adapter (a budget policy for the limiter, a metric set and response parser for observability).
Adding a new outbound API is another adapter, not a change to the mechanism.

## Rate limiting

### Using it

A consumer identifies a budget with a limiter key shaped `{domain}:{scope}:{id}` — e.g. `github:installation:123`.
Go through the facade, never the backing library:

```python
from posthog.rate_limiting import Priority
from posthog.rate_limiting.github import consume_github_installation_sync

if not consume_github_installation_sync(installation_id, priority=Priority.BATCH, source="warehouse"):
    # Budget exhausted — back off and retry, defer, or drop. The limiter never blocks or sleeps.
    raise SomeRetryableError(...)
```

`acquire` (async) and `consume_sync` (sync, for callers outside an event loop) both return `True` if the call fits the shared budget and `False` if it would exceed it.
They are **non-blocking** — the caller decides what to do on `False`.
The GitHub helpers wrap the key construction; other domains expose their own thin gate the same way.

### Budgets (policies)

A budget is a `RatePolicy`: one or more `(count, period_seconds)` limits enforced _together_, so you can cap the hour and smooth per-minute bursts on the same key.
Each domain registers its policy with `register_policy(domain, policy)`, usually as a zero-arg provider so the budget is read from Django settings at acquire time rather than frozen at import.
GitHub's budget is per **installation** (the unit GitHub meters): 13,500 requests/hour plus a 450/minute smoothing cap, deliberately under GitHub's real 15,000/hour ceiling so reactive backoff absorbs drift (clock skew, multi-process races, untracked PAT traffic on the same account).

### Priority lanes

Priority (`CRITICAL` / `NORMAL` / `BATCH`) controls how sheddable a call is when the budget gets tight.
All priorities draw from the _same_ per-key counter — the lane only changes how much headroom must stay free for the call to be admitted (a _reserved floor_), so deferrable bulk traffic (`BATCH`) is denied before critical traffic as the budget fills, without ever splitting the budget into separate buckets.
Admission tests `n + reserve` but only consumes `n`, so an empty reserve is bit-identical to pre-priority behavior.
GitHub ships with no active reserves yet: the mechanism is wired end to end (callers already declare their lane), and turning it on is a one-line change once a `CRITICAL` path is actually gated.

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

- Register a budget with `register_policy("<domain>", provider)` returning a `RatePolicy`.
- Expose a thin per-domain gate that builds the `{domain}:{scope}:{id}` key (see `github.py`).
- For telemetry, register an observability adapter (metric set, response parser, endpoint normalizer) and record responses through it.
- Keep the identity in the external API's id space, and remember the limiter is non-blocking — the caller owns the back-off.
