# Outbound egress: rate limiting, observability, transport

General-purpose controls for the calls PostHog makes _out_ to third-party APIs.
A new outbound integration that needs rate limiting or egress telemetry belongs here as a `<domain>/` package (see [Adding a new egress domain](#adding-a-new-egress-domain)), never hand-rolled around `requests`.
Three lanes, one per subpackage:

- **`limiter/`**: shared, Redis-backed budgets so every worker process draws from one limit and PostHog stays inside an external API's rate limit, with priority lanes so bulk traffic can't starve critical traffic.
- **`observability/`**: the metrics analog, with request volume plus the API's own rate-limit headers, on one Prometheus metric set.
- **`transport/`**: the HTTP client that composes the other two. Each request is gated _and_ recorded by construction, so no caller can bypass either.

This is _outbound_ egress: what PostHog sends.
It is unrelated to `posthog.rate_limit`, which throttles _inbound_ DRF requests from clients.

All three lanes are domain-free.
Each third-party API is a domain under its own subpackage, and that subpackage's `README.md` holds the facts about the API: its identity, budget, lanes and callers, rate-limit headers, and auth.
`github/` is the reference domain.
Read a domain's `README.md` before changing that domain.

## Non-goals

This section records what egress does not do, and why.
Each item below was a real proposal.

**Egress does not store response data.**
The limiter keeps control state about a budget, which stays O(1) per scope and expires on its own, so its footprint does not grow with traffic.
A response body is the opposite, because its footprint tracks request volume.
The test is the entry count, not the entry size.
A small entry per URL still grows with the number of URLs, so a store of validators fails this the same way a store of bodies does.
Storing either therefore needs a size budget, an eviction policy, and a store of its own.
The shared Django cache is not that store, because it also serves the request path.
Cache what a caller needs in that caller's own cache, where the data is already smaller and better shaped than the raw response.

**Egress does not hide an API's response semantics from callers.**
A transport that replays a `304` as a `200`, or an error as an empty result, leaves the caller unable to act on what the API said.
Classify the response instead, and hand the caller a typed result it can act on.
"No call site changes" is not a reason to break this. If a caller has to know that nothing changed, change the caller.

**Egress does not decide what a caller should request.**
A caller that fetches data it does not need is a product bug, and the limiter only makes that bug cheaper to survive.
Fix the request pattern first, then measure what is left.

## Rate limiting

### Using it

A consumer identifies a budget with a limiter key shaped `{domain}:{scope}:{id}`, for example `github:installation:123`.
Go through the domain's gate, never the backing library:

```python
from posthog.egress.limiter.policies import Priority
from posthog.egress.github.limiter import consume_github_installation_sync

if not consume_github_installation_sync(installation_id, priority=Priority.BATCH, source="warehouse"):
    # Budget exhausted: back off and retry, defer, or drop. The limiter never blocks or sleeps.
    raise SomeRetryableError(...)
```

`acquire` (async) and `consume_sync` (sync, for callers outside an event loop) both return `True` if the call fits the shared budget and `False` if it would exceed it.
They are **non-blocking**: the caller decides what to do on `False`.
Each domain wraps the key construction in a thin gate like the GitHub helper above.

### Pacing (for callers that can wait)

Getting denied is recoverable but wasteful: the caller learns nothing about _when_ the budget frees, so it backs off blind, and the budget it already spent stays spent.
A caller that can wait (a bulk import walking pages, not a request serving a person) should instead ask how long to wait and not get denied at all:

```python
pace = get_outbound_rate_limiter().pace_seconds(key, priority=Priority.BATCH)
if pace > 0:
    ...  # the caller owns the wait; the limiter never sleeps
```

`pace_seconds` returns **0 while a window still holds more than half of that priority's allowance**, so a short run is never slowed for a budget it cannot dent.
Below that it spreads the allowance that is left over the time left in the window, which is the interval that keeps the caller admitted instead of shed.
It reads the same reserved floors admission does, so a `BATCH` caller paces off the share it may actually take, not the whole window.
A caller that keeps several calls in flight also asks `admission_interval_seconds(key, priority=...)` for the gap between admissions that fits its share of every window, and waits for whichever of the two is longer.
`pace_seconds` reads the window, so it cannot see calls the caller admitted but has not consumed yet; the interval comes from the policy alone and holds through that gap and through a store outage.

Two things it is not.
It is **advisory**: `acquire`/`consume_sync` remain the only authority on whether a call is admitted, so a bug here cannot over-admit.
And it is not a wait-for-reset: these are sliding windows, which free continuously, so waiting for a reset would idle for a whole window to get budget that was arriving all along.
A store failure answers 0 rather than raising, because pacing sits in front of every gated call and the in-memory fallback's headroom is one process's, not the shared budget's.

### Budgets (policies)

A budget is a `RatePolicy`: one or more `(count, period_seconds)` limits enforced _together_, so a policy can cap the hour and smooth per-minute bursts on the same key.
Each domain registers its policy with `register_policy(domain, provider)`.
A provider takes the full limiter key and runs at acquire time, so the budget follows settings changes and per-scope state rather than freezing at import.
Most domains use `per_minute_and_hourly_policy`, which reads a per-minute and an hourly ceiling from settings.

Where the provider publishes a limit, the budget stays under it, so the caller's reactive backoff absorbs drift (clock skew, multi-process races, traffic PostHog does not count).
Where the provider publishes none, the budget is an operator ceiling on spend, meant to be raised in settings as real traffic grows.

### Priority lanes

Priority (`CRITICAL` / `NORMAL` / `BATCH`) controls how sheddable a call is when the budget gets tight.
All priorities draw from the _same_ per-key counter.
The lane only changes how much headroom must stay free for the call to be admitted (a _reserved floor_), so deferrable bulk traffic (`BATCH`) is denied before critical traffic as the budget fills, without ever splitting the budget into separate buckets.
Admission tests `n + reserve` but only consumes `n`.

Every policy gets `DEFAULT_RESERVE` unless it passes its own: `BATCH` calls are denied once 70% of a window is consumed and `NORMAL` at 90%, while `CRITICAL` may use the full budget.
A policy passes `reserve={}` only when no higher-priority traffic exists to protect, and its limiter docstring says why.
`test/test_domains.py` lists the flat domains, so a new flat policy needs a reviewed change to that list.

A denied sheddable call raises the domain's `EgressBudgetExhausted` subclass.
A denied `CRITICAL` call proceeds, and the API's own 429 is the backstop.

### Backend

A sliding-window counter over Redis holds the shared budget across worker processes: O(1) memory per key, self-expiring, no background grooming.
When Redis is unavailable it degrades to a per-process in-memory counter, shrunk by `in_memory_divider` so N processes don't together allow N× the shared limit.
That fallback is best-effort: **the consumer's reactive backoff (e.g. honoring a 429) is the real backstop**, and the limiter is a proactive smoother on top.
All library and Redis specifics live in the backend module, so the facade and consumers stay backend-agnostic and the algorithm stays swappable.

## Egress observability

Each domain constructs one `EgressObservability`, and the domain's transport records every request through it.
Request volume and the API's rate-limit headers land on one metric set, whichever subsystem made the call.

- **Counter** (for example `github_integration_api_requests_total`): request volume, always recorded, including errors, rate-limited responses, and transport exceptions that raise before a response. Labeled `<scope>, method, endpoint, status_code, source`.
- **Gauges** (for example `github_integration_api_rate_limit_remaining`): last-observed budget headroom parsed from the API's response headers. Labeled `<scope>, resource`, with no `source`, because the budget is shared across sources. The gauges are optional: a domain declares only the ones its API reports, and parses only headers the API documents.
- **Decisions** (`outbound_rate_limit_decisions_total`): one sample per limiter admission, labeled `domain, source, priority, granted`.

Each domain keeps its own metric names, so existing dashboards stay valid.
The `source` label (e.g. `integration`, `visual_review`, `warehouse`) carries per-subsystem attribution.
Endpoint labels are normalized to bound cardinality: numeric ids are templated out by default, and a domain with structured paths passes its own normalizer, so raw-URL callers don't mint one label per id.

Harmonic also records `harmonic_api_request_duration_seconds` from the start of an HTTP request through response headers, and `harmonic_api_admission_wait_seconds` for waits in the bulk client's pacing loop, including time queued for the pacing lock.
The request duration excludes the local admission wait and response-body parsing.
The weekly Salesforce sweep allows 24 company lookups in flight; each outbound request still draws from the shared BATCH budget.

## Transport

`transport/transport.py` holds three bases:

- **`EgressClient`**: gate, request, record, for a sync domain with a budget. A subclass sets `observability`, draws from its budget in `_consume`, and names its `EgressBudgetExhausted` subclass.
- **`RecordedEgressClient`**: request and record with no gate, for an API that publishes no request limit a rate budget can model. `slack/` and `vapi/` use it.
- **`AsyncEgressClient`**: the gated algorithm over aiohttp. `harmonic/` uses it.

A domain exposes a `<domain>_request` helper over its client, and may add a typed client for the few endpoints its callers use (see `firecrawl/client.py`).
A domain whose callers go through a vendor SDK hooks the SDK instead (see `slack/client.py`).
Every client is token-agnostic: the caller passes its own credentials.
Response handling, such as what to do on a 403 or 429, stays with the caller.

Two semgrep rules in `.semgrep/rules/devex/` fail CI on a raw call that bypasses a domain: `github-api-calls-go-through-egress` (a `requests` call that names `api.github.com`) and `slack-api-calls-go-through-egress` (a `requests` call that names `slack.com/api`, or a bare `WebClient`).
The `requests` half of each rule reads the URL argument only, so a call that binds the URL to a variable first gets through. Keep the URL inline at the call site.
No rule covers the other domains.

## The one identity rule

Everything keys on the **budget owner in the external API's own id space**: for GitHub the App **installation id**, because that is what GitHub meters.
It is **never** a PostHog DB row id (`Integration.id`).
Several PostHog integration rows can point at the same installation (multiple projects, one org), and GitHub gives that installation one shared budget: key a gauge by the row and one real budget splits into N flip-flopping series; key by the installation and you get one true series.
Per-caller attribution is the `source` label's job, not the identity's.

An identity that must not reach a metric label in plain form, such as a token, is hashed first (see `browserless/` and `vapi/`).
A caller with no identity in scope passes no scope: it records the counter only and skips both the limiter and the gauges.

## Adding a new egress domain

Add a `<domain>/` subpackage and work through this list.
The `/routing-outbound-api-calls` agent skill names the reference domain to copy and carries the decisions behind each step.

1. **Choose the base.** `EgressClient` when the API publishes a limit or bills per call, `RecordedEgressClient` when only telemetry is useful, `AsyncEgressClient` for an aiohttp client.
2. **Pick the identity** in the external API's id space (see [The one identity rule](#the-one-identity-rule)).
3. **For a gated domain, add `limiter.py`.** Register a policy (usually `per_minute_and_hourly_policy`) and a thin gate that builds the `{domain}:{scope}:{id}` key. Keep the default reserve unless no higher lane exists; a flat policy needs a docstring reason and an entry in `test/test_domains.py`.
4. **Add `observability.py`** with one `EgressObservability` and the domain's metric names. Declare a gauge and parse a header only when the API documents it.
5. **Add `transport.py`** with the client subclass and a `<domain>_request` helper.
6. **Add `README.md`** with the sections the other domains use: Identity, Budget, Lanes and callers, Rate-limit headers, Auth, Sources. Sources links the vendor page behind each limit, cost, and header claim. `test/test_domains.py` fails without the README or its Sources section.
7. **Test the real policy** for any claim about which lane sheds first. A test that patches the gate cannot see a missing reserve.

Keep the subpackage free of `posthog.models` imports, and remember the limiter is non-blocking: the caller owns the back-off.
