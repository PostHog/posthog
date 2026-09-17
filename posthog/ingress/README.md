# Inbound ingress: verification, dispatch, transport

General-purpose controls for the webhooks third parties send _in_ to PostHog.
A new inbound webhook that needs signature verification or fan-out belongs here as a `<provider>/` incarnation (see [Adding a provider](#adding-a-provider)), never hand-rolled around `hmac` in a view.
Four lanes:

- **`verify/`** — signature schemes. HMAC-SHA256 in the shapes providers actually send (hex or base64, an optional prefix, an optional `v0:{timestamp}:{body}` input with a replay window), plus the SNS envelope check.
- **`dispatch/`** — the validated consumer registry, per-delivery dedup, the wall-clock budget, consumer isolation, and `bounded_statement_timeout()` for consumers that read the database.
- **`observability/`** — Prometheus: delivery volume by transport outcome, and one metric set per consumer run.
- **`views.py`** — the view that composes the other three: one request that is verified _and_ recorded by construction, so no incarnation can skip either.

Two more modules sit at the package root because every lane and every incarnation speaks them: `contracts.py` holds the three values (`WebhookDelivery`, `WebhookConsumer`, `ProviderSpec`), and `providers.py` holds the `WebhookProvider` base each incarnation subclasses plus the lazy import list that finds the incarnations.

This is _inbound_ ingress — what PostHog receives.
It is the sibling of `posthog/egress/`, which is what PostHog sends, and unrelated to `posthog.rate_limit`, which throttles inbound DRF requests from PostHog's own clients.

All four lanes are **provider-generic**; each third party is an incarnation under its own subpackage, supplying header names, a scheme, and how to read an event type and a delivery id off the request.
Each provider has a `README.md` in its folder, which holds its headers, its scheme, its apps and secrets, its quirks and its consumers.
Adding a provider is another `<provider>/` folder, not a change to the mechanisms.

## The lanes one request runs through

`build_webhook_view()` runs the same lanes for every provider, in this order:

1. **Method** — anything but `POST` is 405, before any secret is read.
2. **Throttle** — `provider.throttle_class`, when the provider sets one. A refusal is 429 with a `Retry-After`.
3. **Verify** — `provider.verify(request)` over the raw body, answering a `Verification`. A bad signature never reaches a consumer.
4. **Parse** — `provider.parse(request)`, which decodes the verified body. The default is JSON; an `InvalidPayload` is 400.
5. **Handshake** — `provider.pre_dispatch_response(request, payload)`, for a challenge the protocol demands.
6. **Dispatch** — `provider.deliveries(request, payload, facts)`, then ownership, the forward and the consumers, all inside one wall-clock budget.

Parse belongs to the provider because not every third party posts JSON: Slack's interactivity payloads and Mailgun's events are form-encoded.
It stays **after** verification, and must: a `parse` that reads `request.POST` consumes the request stream under ASGI, which leaves the signature check without the raw bytes it signs over.

The throttle sits **in front of** verification, because on a provider that signs with a JWT the verification is the expensive half.
An unsigned request buys a signing-key lookup, so the cap has to be reached first or it caps nothing worth capping.
`throttle_class` takes a DRF throttle from `posthog.rate_limit`, which is where every other rate belongs.
A provider whose verification is a local HMAC leaves it at `None`.

A `Verification` carries the outcome and `facts`, a mapping of what the check proved on the way.
A scheme that validates a signed token knows who sent the delivery before the body is read, and `facts` is how those claims reach `deliveries`, so an incarnation can cross-check the body against what was actually signed rather than trusting a field of the body that claims the same thing.
An HMAC over raw bytes proves only the signature, so its `facts` are empty and `deliveries` ignores the argument.

## Endpoints

| Provider     | Path                                                    | App          | Consumers                                                                                                                                   | Product code                                                            |
| ------------ | ------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `github`     | `/webhooks/github`, `/webhooks/github/pr`               | `posthog`    | `installation_lifecycle`, `installation_repositories` (core), `conversations`, `loops`, `tasks_pr_backstop`, `tasks_pr_review`, `workflows` | `products/{tasks,conversations,workflows}/backend/webhook_consumers.py` |
| `github`     | `/webhooks/stamphog/github`                             | `stamphog`   | `stamphog_review`                                                                                                                           | `products/stamphog/backend/webhook_consumers.py`                        |
| `slack`      | `/api/conversations/v1/slack/events`                    | `supporthog` | `conversations_slack`                                                                                                                       | `products/conversations/backend/webhook_consumers.py`                   |
| `pandadoc`   | `/api/legal_documents/pandadoc`                         | `default`    | `legal_documents_signatures`                                                                                                                | `products/legal_documents/backend/webhook_consumers.py`                 |
| `vapi`       | `/api/user_interviews/vapi_webhook/`                    | `default`    | `user_interviews_vapi`                                                                                                                      | `products/user_interviews/backend/webhook_consumers.py`                 |
| `mailgun`    | `/api/conversations/v1/email/inbound`                   | `inbound`    | none yet, the endpoint still runs its own verifier                                                                                          | `products/conversations/backend/api/email_events.py`                    |
| `mailgun`    | `/api/conversations/v1/email/outbound`                  | `outbound`   | none yet, the endpoint still runs its own verifier                                                                                          | `products/conversations/backend/api/email_events.py`                    |
| `sns`        | `/webhooks/workflows/ses-events`                        | `default`    | `workflows_ses_events`                                                                                                                      | `products/workflows/backend/webhook_consumers.py`                       |
| `customerio` | `/api/projects/<team_id>/messaging/customerio/webhook/` | none         | none, it is the DRF adapter path                                                                                                            | `products/messaging/backend/api/customerio_webhook.py`                  |

The owner of the third-party App registration owns the route.
The customer-facing GitHub App is shared across products, so its two endpoints are declared in `posthog/urls.py`.
Every other endpoint is declared by the product that registered the App, in its own `routes.py`.
The SES endpoint is the exception for now, because its view still lives in `backend/api/` rather than behind the ingress builders.

The Vapi endpoint sits behind a per-IP throttle the product owns, from before ingress had a throttle lane.
It moves onto `throttle_class` next.

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
If a provider's protocol needs the response body to say something, the incarnation answers that handshake before dispatch.

What the transport does decide is whether it can vouch that the delivery was taken.
It cannot when an ownership lookup failed, when the forward to the owning region failed, when a consumer raised, or when the budget skipped a consumer — in each case some of the work never ran, or ingress cannot tell whether it ran in the right region.
A provider that redelivers on a non-2xx sets `retry_status` on its incarnation, and the view then answers that status with outcome `retry_requested` instead of the receipt, so the provider sends the delivery again.
A provider that does not redeliver leaves it at `None` and keeps the receipt, because a non-2xx buys it nothing.
That is still the transport deciding, on whether the work ran at all, rather than a consumer choosing an answer: a consumer cannot ask for a retry, and a delivery no consumer is registered for is accepted by construction.

The cost is fan-out: a retry replays the delivery against every consumer on the endpoint, not only the one that failed.
Dedup is what keeps that cheap — a consumer that already accepted the delivery is deduped on the redelivery, and only the one that raised or never started runs again.
A consumer with `dedup=False` runs on every redelivery, so a sibling that keeps failing makes it repeat its work.

**Ingress does not promise an order.**
Consumers are independent by construction; anything that depends on another consumer's result belongs in one consumer.
The dispatcher iterates sorted by name so logs and metrics are stable, but that is an implementation detail and not a contract.

## Contracts

```python
from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery
```

`WebhookDelivery` is one verified, parsed delivery: provider, app, delivery id (`None` when the provider sends none), event type, payload, receipt time, and a small string-valued `context` for provider extras such as an installation id or Slack's retry headers.
One request can become several deliveries, because a provider can batch several events into one body.

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
On a provider that sets `retry_status` a handler that raises also costs the request its receipt, so the provider redelivers rather than waiting for a sweeper to notice.
That is what a consumer whose durable record is written inside the handler needs: nothing else is holding the delivery.

`dedup=False` turns the mark off for one consumer.
That is right when the consumer already keys its own recovery on the provider's delivery id, so a redelivery is how work that never finished gets picked up.
Leave it on everywhere else: without an idempotency key of its own, a consumer that opts out does the work again on every redelivery.

## The delivery budget

Every request gets one wall-clock budget, `INGRESS_DELIVERY_BUDGET_SECONDS` (default 8).
Consumers draw from it in turn, across every delivery the request carries, because a request that batches several events would otherwise hold the connection open for one budget per event.
When it is spent, the consumers that have not started are skipped with outcome `budget_exceeded` and a warning that names them, and they are **not** marked in dedup — so the provider's redelivery reaches them.
On a provider that sets `retry_status` a skipped consumer also costs the request its receipt, which is what makes that redelivery happen rather than waiting for the next event.

The budget is a backstop, not a scheduler: it cannot interrupt a consumer that is already running.
A consumer that touches the database on this path wraps its reads in `bounded_statement_timeout(ms, models=...)`, which installs `SET LOCAL statement_timeout` on each alias those models route to.
Pass the models rather than capping every configured alias: opening an alias is itself unbounded, so reaching for one the read never uses can stall the delivery on connection setup before the cap is even installed.

Both controls exist because the incidents on the GitHub webhook path came from unbounded query cost against a shared connection pool, not from running consumers inside the request.
The fixes that worked bounded the queries: [#83852](https://github.com/PostHog/posthog/pull/83852) scoped the run lookup to the installation's teams and put a statement timeout on the attribution lookup, and [#87779](https://github.com/PostHog/posthog/pull/87779) added the indexes it needed.
Ingress carries both as general controls, so the next endpoint gets them without rediscovering the same failure.

## Regional forwarding

A third party holds one callback URL, which points at the primary region (EU), so a delivery about a resource the other region (US) owns still arrives here first.
Ingress owns the forward, because what is replayed is the signed body — a consumer only ever sees the parsed mapping.

A consumer whose resources are split by region declares `ownership`, a callable that takes the delivery and answers a `DeliveryOwnership`:

- `LOCAL` — this region holds the resource. Nothing changes: local dispatch always runs.
- `ELSEWHERE` — the other region holds it. The request is forwarded.
- `UNDECIDED` — nothing in the delivery says, so nothing is forwarded.

A fourth value, `FAILED`, is the dispatcher's own: a consumer never answers it, and it records a lookup that raised.

Every delivery in the request is assessed first, and the request is then forwarded **once**, when any consumer answered `ELSEWHERE`.
One forward per request rather than per delivery, because the unit being replayed is the HTTP request.
Local dispatch runs either way: a consumer that answered `ELSEWHERE` no-ops on its own, and the other consumers on the endpoint are unaffected.
Only the primary region forwards; on the secondary region an `ELSEWHERE` answer is logged as `ingress_delivery_unowned_here`, because a local miss there is that consumer's unresolved routing rather than proof that no region owns the delivery.
The replay carries the signed bytes and the provider's own headers, but never the headers that name the host this region answered on: `Host`, `X-Forwarded-Host`, `X-Forwarded-Port`, `X-Forwarded-Proto` and `Forwarded`.
The receiving region reads which region it is off the connection it receives, so a forwarded host would make it forward the delivery on again.

The ownership lookup runs inside the request, before dispatch, and inside the same wall-clock budget.
A lookup that reads the database must be bounded with `bounded_statement_timeout(ms, models=...)`.

A lookup that raises is logged, captured and counted as `failed`, and it rules no region out.
On a provider that sets `retry_status` the view answers that status with outcome `retry_requested`, before the forward and before any consumer runs.
Local dispatch alone would otherwise receipt the delivery: the consumer's own lookup runs again inside the handler, correctly finds nothing local, the handler returns, and the region that owns the delivery never sees it.
Nothing has claimed a dedup mark at that point, so the redelivery is processed in full, and the lookups it asks again decide the forward then.
A provider that does not redeliver keeps the delivery instead: the failure counts as `UNDECIDED`, local dispatch runs, and the request is receipted, because a non-2xx there would only lose the local run as well.

An ownership lookup should therefore let a transient error out rather than answering `LOCAL` or `UNDECIDED` through it.
A guess is what turns a dropped connection into a lost delivery.

What crosses is the raw signed body, except for a provider that signs the form rather than the body.
Reading that form consumes the request stream and leaves no raw bytes, so the forward rebuilds the fields and the files and drops the original `Content-Type`, which names the boundary of a body that is gone.

The forward runs under the provider's `forward_timeout_seconds`, which defaults to 3 and which a provider whose deliveries carry uploaded files raises, because the forward rebuilds and re-sends every part.

A failed forward keeps the receipt by default.
A provider that redelivers on a non-2xx (Slack does, GitHub does not) sets `retry_status` on its incarnation, and the view answers that status with outcome `forward_failed` instead — so the provider sends the delivery again rather than losing it.
The same attribute answers a delivery whose consumers did not accept it, under outcome `retry_requested`; see ["Ingress does not let a consumer decide the response"](#non-goals).

## Adding a provider

Add a `<provider>/` subpackage with a `provider.py` holding three things (see `github/` for the full shape, `vapi/` for a small one):

- `SPECS` — one `ProviderSpec` per app, naming the event types the app is subscribed to. The registry validates consumers against these.
- A `WebhookProvider` subclass — its `scheme()` (from `verify/`), its `deliveries()` (how to read event type, delivery id and context off the request), and any status codes its protocol fixes. The defaults are 403 on a bad signature, 500 when unconfigured, and 202 on success, with a short body naming the reason on the two rejections. An incarnation that answers 404 to withhold the endpoint's existence sets `explains_rejections = False` so the body stays empty as well. Three more attributes are optional: `parse()`, which decodes the body, `throttle_class`, which caps request volume, and `retry_status`, which a provider that redelivers on a non-2xx sets so an unaccepted delivery is not receipted. See [The lanes one request runs through](#the-lanes-one-request-runs-through).
- A `build_<provider>_provider(...)` function returning that provider, which the URLconf hands to `build_webhook_view()`.

Add the module to `_INCARNATION_MODULES` in `posthog/ingress/providers.py`, so the registry finds its specs and any core consumers.

Then mount the URL where the App registration lives.
A product that registered the App declares the path in its own `products/<product>/backend/routes.py`, under a `webhooks/<product>/` prefix:

```python
urlpatterns: list[URLPattern] = [
    opt_slash_path("webhooks/stamphog/github", build_webhook_view(build_github_provider("stamphog"))),
]
```

An App several products consume has no single owner, so it stays in `posthog/urls.py`.
The customer-facing GitHub App is the only one today.
[docs/internal/url-routing.md](../../docs/internal/url-routing.md) has the slot and the prefix rule.

Secrets and verifiers that belong to a product are **passed into the builder**.
Nothing under `posthog/ingress/` imports a product.

A consumer no product owns is registered by the incarnation itself, in a `CORE_CONSUMERS` tuple next to `SPECS`.

Last, write `<provider>/README.md` with the fixed sections every provider README carries: headers, signature scheme, delivery id and event type, apps and secrets, quirks, consumers.
`posthog/ingress/test/test_provider_readme_sections.py` fails on a provider folder without one.

Two shapes that already exist and are worth copying rather than re-deriving:

- **Several apps on one provider.** One incarnation can serve several apps, each with its own secret getter, its own subscribed event types, and its own consumer set. Consumers register against the app name. `github/` is the case.
- **A provider that signs the form rather than the body.** The incarnation overrides both `verify()` and `parse()` to read `request.POST`, assembles the signed input from the form fields, and hands it to `HmacSha256` as if it came from headers. `mailgun/` is the case.
- **The DRF adapter path.** An endpoint that genuinely needs DRF's team scoping keeps its view, and the incarnation contributes a scheme only, declaring no spec, because nothing dispatches there. `customerio/` is the case. The view verifies through `posthog.auth.WebhookSignatureAuthentication`.
  That base class computes its digest with `hmac_sha256_signature()` and compares with `signatures_match()` from `verify/schemes.py`, so the adapter path and the dispatched path share one implementation of HMAC-SHA256.
  It backs three endpoints rather than Customer.io alone, because the tasks cross-region usage lookup and the AI observability cross-region spend lookup subclass it too, each with its own header names, signed-input format, and secret.

## Dedup

Dedup is per `(provider, consumer, delivery_id)` in the Django cache, for 24 hours.
The mark is set before the consumer runs and released when it raises, so a failure does not burn the delivery for a day.
Because it is set before the work finishes, it carries a state rather than a bare flag: a claim answers `CLAIMED`, `IN_PROGRESS` or `DONE`, and the consumer settles it to done when it returns.
Only `DONE` counts as accepted, so a delivery that meets a run still in flight is skipped with outcome `in_flight` and is not receipted, and a provider with `retry_status` sends it again once the first run settled rather than trusting a run that can still fail.
Keying per consumer rather than per delivery matters: one delivery legitimately fans out to several consumers, and a delivery-wide key would starve every consumer but the first.
A cache error fails **open** — dropping deliveries during a cache outage is worse than running a consumer twice, and consumers carry their own idempotency underneath this.

A provider that sends no delivery id skips dedup entirely, and its own README says why it has none.

## Observability

- **`posthog_ingress_deliveries_total{provider,app,outcome}`** — what the transport answered: `accepted`, `method_not_allowed`, `throttled`, `not_configured`, `invalid_signature`, `invalid_payload`, `forward_failed`, `retry_requested`. A consumer failure lands here only on a provider that sets `retry_status`; everywhere else it is counted on the consumer metric alone, because the delivery still gets its receipt.
- **`posthog_ingress_consumer_runs_total{provider,consumer,outcome}`** — `succeeded`, `failed`, `deduped`, `budget_exceeded`, `in_flight`.
- **`posthog_ingress_consumer_duration_seconds{provider,consumer}`** — where a delivery's budget actually went.
- **`posthog_ingress_ownership_total{provider,consumer,outcome}`** — what a consumer answered when asked which region owns the delivery: `local`, `elsewhere`, `undecided`, `failed`.
- **`posthog_ingress_forwards_total{provider,app,outcome}`** — what the owning region answered a forwarded request: `forwarded`, `rejected`, `failed`.
- **`ingress_delivery_invalid_payload`** — a warning log with the parser error text for a verified delivery whose body did not parse. The counter above cannot carry that text.

A secret in a URL or header is the credential and never becomes a metric label.
