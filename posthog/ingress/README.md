# Inbound ingress: verification, dispatch, transport

General-purpose controls for the webhooks third parties send _in_ to PostHog.
GitHub was the first provider and the others follow the same shape.
A new inbound webhook that needs signature verification or fan-out belongs here as a `<provider>/` incarnation (see [Adding a provider](#adding-a-provider)), never hand-rolled around `hmac` in a view.
Four lanes:

- **`verify/`** — signature schemes. HMAC-SHA256 in the shapes providers actually send (hex or base64, an optional prefix, an optional `v0:{timestamp}:{body}` input with a replay window), plus the SNS envelope check.
- **`dispatch/`** — the validated consumer registry, per-delivery dedup, the wall-clock budget, consumer isolation, and `bounded_statement_timeout()` for consumers that read the database.
- **`observability/`** — Prometheus: delivery volume by transport outcome, and one metric set per consumer run.
- **`views.py`** — the view that composes the other three: one request that is verified _and_ recorded by construction, so no incarnation can skip either.

Two more modules sit at the package root because every lane and every incarnation speaks them: `contracts.py` holds the three values (`WebhookDelivery`, `WebhookConsumer`, `ProviderSpec`), and `providers.py` holds the `WebhookProvider` base each incarnation subclasses plus the lazy import list that finds the incarnations.

This is _inbound_ ingress — what PostHog receives.
It is the sibling of `posthog/egress/`, which is what PostHog sends, and unrelated to `posthog.rate_limit`, which throttles inbound DRF requests from PostHog's own clients.

All four lanes are **provider-generic**; each third party is an incarnation under its own subpackage (`github/`, `slack/`, `pandadoc/`, `vapi/`, `sns/`, `customerio/`), supplying header names, a scheme, and how to read an event type and a delivery id off the request.
Adding a provider is another `<provider>/` folder, not a change to the mechanisms.

## Non-goals

This section records what ingress does not do, and why.

**Ingress does not store a delivery log.**
A delivery record's footprint tracks inbound volume, which is set by the third party rather than by PostHog, so it has no natural ceiling.
Storing one therefore needs a size budget, an eviction policy, and a store of its own.
The dedup mark is the opposite: it is O(1) per delivery, expires on its own, and holds no payload.
A consumer that needs the payload later writes its own receipt, as conversations already does.

**Ingress does not queue, retry, or dead-letter.**
The provider already retries, and it knows things PostHog does not: how many attempts are left, and when to give up.
A second retry layer on this side would deliver the same event twice under two different clocks.
A consumer that wants asynchronous work enqueues its own task and answers immediately, which is what conversations and stamphog do.

**Ingress does not let a consumer decide the response.**
The HTTP response is a transport receipt: the verification result, the method, and the payload decide the status, and consumer return values are ignored.
A consumer that fails must not turn a verified delivery into a 500 the provider will replay against every other consumer too.
If a provider needs the body to say something (Slack's `url_verification` challenge), the incarnation answers it before dispatch.

**Ingress does not promise an order.**
Consumers are independent by construction; anything that depends on another consumer's result belongs in one consumer.
The dispatcher iterates sorted by name so logs and metrics are stable, but that is an implementation detail and not a contract.

## Contracts

```python
from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery
```

`WebhookDelivery` is one verified, parsed delivery: provider, app, delivery id (`None` when the provider sends none), event type, payload, receipt time, and a small string-valued `context` for provider extras such as an installation id or Slack's retry headers.
One request can become several deliveries — PandaDoc batches events into one body.

`WebhookConsumer` is a handler registered for some of a provider app's event types.
Its `name` is part of the dedup cache key, so **renaming a consumer lets a redelivery run it twice**.
Treat the name as fixed once it ships.

## Adding a consumer

A product declares `products/<name>/backend/webhook_consumers.py` with a `WEBHOOK_CONSUMERS` sequence:

```python
WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="loops",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment", "pull_request", "push"}),
        handler=handle_github_event_for_loops,
    ),
)
```

The registry finds these through `posthog.products.load_product_modules("webhook_consumers")` on the **first delivery**, not at `django.setup()`.
That is deliberate: eager loading would drag every product's webhook module onto the startup import path, which `posthog/test/repo_invariants/test_startup_import_budget.py` exists to keep clear.
Keep the module itself cheap to import and defer the heavy work into the handler.

Registration is validated and fail-closed.
A consumer that names a provider app nobody declares, reuses a name already taken for that provider, or registers for an event type the provider does not declare raises `RegistryError` at build, rather than sitting there looking registered and never running.

A handler takes one `WebhookDelivery` and returns nothing.
It runs synchronously inside the request, isolated: raising is logged and captured, and it releases its own dedup mark so the provider's redelivery reaches it again.

## The delivery budget

Every request gets one wall-clock budget, `INGRESS_DELIVERY_BUDGET_SECONDS` (default 8).
Consumers draw from it in turn, across every delivery the request carries, because a request that batches (PandaDoc) would otherwise hold the connection open for one budget per event.
When it is spent, the consumers that have not started are skipped with outcome `budget_exceeded` and a warning that names them, and they are **not** marked in dedup — so the provider's redelivery reaches them.

The budget is a backstop, not a scheduler: it cannot interrupt a consumer that is already running.
A consumer that touches the database on this path wraps its reads in `bounded_statement_timeout(ms, models=...)`, which installs `SET LOCAL statement_timeout` on each alias those models route to.
Pass the models rather than capping every configured alias: opening an alias is itself unbounded, so reaching for one the read never uses can stall the delivery on connection setup before the cap is even installed.

## Adding a provider

Add a `<provider>/` subpackage with a `provider.py` holding three things (see `github/` for the full shape, `vapi/` for a small one):

- `SPECS` — one `ProviderSpec` per app, naming the event types the app is subscribed to. The registry validates consumers against these.
- A `WebhookProvider` subclass — its `scheme()` (from `verify/`), its `deliveries()` (how to read event type, delivery id and context off the request), and any status codes its protocol fixes. The defaults are 403 on a bad signature, 500 when unconfigured, and 202 on success.
- A `build_<provider>_provider(...)` function returning that provider, which the URLconf hands to `build_webhook_view()`.

Then register the URL as usual:

```python
path("webhooks/github/", build_webhook_view(build_github_provider("posthog")))
```

Secrets that belong to a product (Slack's signing secret, the SNS verifier and topic allowlist) are **passed into the builder**.
Nothing under `posthog/ingress/` imports a product.

Two shapes that already exist and are worth copying rather than re-deriving:

- **Several apps on one provider.** `github/` serves both the customer-facing PostHog App and the Stamphog review App. Each app has its own secret getter, its own subscribed event types, and its own consumer set, and consumers register against the app name.
- **The DRF adapter path.** Customer.io keeps its DRF view, because it is team-scoped, its secret comes from that team's integration row, and it needs no fan-out. `customerio/` contributes a scheme only and declares no spec; `posthog.auth.WebhookSignatureAuthentication` does the verifying. Reach for this only when an endpoint genuinely needs DRF's team scoping.

## Dedup

Dedup is per `(provider, consumer, delivery_id)` in the Django cache, for 24 hours.
The mark is set before the consumer runs and released when it raises, so a failure does not burn the delivery for a day.
Keying per consumer rather than per delivery matters: one delivery legitimately fans out to several consumers, and a delivery-wide key would starve every consumer but the first.
A cache error fails **open** — dropping deliveries during a cache outage is worse than running a consumer twice, and consumers carry their own idempotency underneath this.

Providers that send no delivery id (PandaDoc, Vapi) skip dedup entirely.
Vapi does send a call id, but it repeats across the status update and the end-of-call report, so it cannot key dedup without swallowing the second one.

## Observability

- **`posthog_ingress_deliveries_total{provider,app,outcome}`** — what the transport answered: `accepted`, `method_not_allowed`, `not_configured`, `invalid_signature`, `invalid_payload`. A consumer failure is not here, because a failing consumer still gets a 2xx receipt.
- **`posthog_ingress_consumer_runs_total{provider,consumer,outcome}`** — `succeeded`, `failed`, `deduped`, `budget_exceeded`.
- **`posthog_ingress_consumer_duration_seconds{provider,consumer}`** — where a delivery's budget actually went.
