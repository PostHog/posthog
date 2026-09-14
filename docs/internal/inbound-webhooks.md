# Inbound webhooks

A webhook a third party sends to PostHog goes through `posthog/ingress/`.
The package verifies the signature, parses the delivery, and runs the consumers that registered for it.
That is the rule for a new endpoint; the endpoints that predate the package are migrating one at a time, and the PR adding this page wires Stamphog only (see [Endpoints today](#endpoints-today)).
Read this page before you add an endpoint or a consumer.
[`posthog/ingress/README.md`](../../posthog/ingress/README.md) holds the package's own reference: the lanes, the dedup rules, and the metric names.

A hand-rolled `hmac` check in a view is not the way in.
The `inbound-webhooks-go-through-ingress` semgrep rule turns that shape into a CI failure: it catches a signature comparison in a view or in a per-product verifier helper.
The rule ships in its own PR, not this one (see [The semgrep rule](#the-semgrep-rule)).

## The transport contract

The HTTP response is a receipt for the transport, not a report on the work.
Three things decide the status:

- The method. Anything but `POST` answers 405.
- The signature. A bad one answers the provider's configured status, 403 by default. A missing secret answers 500 by default, because it is an operator problem rather than a caller one.
- The payload. A body that is not JSON answers 400.

Everything else answers 202.
A provider incarnation may fix its own codes where the protocol demands it.
PandaDoc answers 404 on a bad signature, so a prober cannot tell a wrong secret from an unknown route.
Vapi answers 401 on a bad signature and 503 when unconfigured, which its public interview surface already relies on.

Consumers never decide the status, and their return values are ignored.
A consumer that raises is logged and captured, and the provider still gets the receipt it earned by signing the request.
A consumer that turned a verified delivery into a 500 would make the provider replay that delivery against every other consumer too.

One request carries one wall-clock budget, `INGRESS_DELIVERY_BUDGET_SECONDS`, which defaults to 8 seconds.
Consumers draw from it in turn.
When it is spent, the consumers that have not started are skipped with the outcome `budget_exceeded` and a warning that names them.
Those consumers get no dedup mark, so the provider's redelivery reaches them.
The budget is a backstop and not a scheduler: it cannot interrupt a consumer that is already running.

Dedup is per `(provider, consumer, delivery id)` in the Django cache, for 24 hours, under the key `webhook_delivery:{provider}:{consumer}:{delivery_id}`.
The mark is set before the consumer runs and released when it raises.
The consumer name is therefore part of the key.
**Treat a consumer name as fixed once it ships**: renaming one lets a redelivery run it a second time.
A provider that sends no delivery id skips dedup, and its consumer carries its own idempotency instead.
A consumer can also opt out with `dedup=False`, which is right when it already keys its own recovery on the delivery id: the mark would otherwise stop a redelivery from ever reaching that recovery path.
Stamphog is the case today. Leave the flag alone unless the consumer has an idempotency key of its own, because an opted-out consumer redoes the work on every redelivery.

## How a request becomes deliveries

The view verifies the request, parses the body once, and asks the provider incarnation for the deliveries in it.
One request usually becomes one delivery, but not always.
PandaDoc batches several events into one body, so its incarnation yields one delivery per batched event, and all of them share the request's budget.

Between verification and dispatch the provider incarnation gets one look at the raw request, through `pre_dispatch_response()`.
Returning a response there answers the caller and runs no consumer.
Returning `None` lets dispatch continue.
`pre_dispatch_response()` is a method on the `WebhookProvider` base, so an incarnation overrides it.
Only two things belong there:

- A handshake the protocol demands. Slack's `url_verification` challenge must be echoed in the body, so the Slack incarnation overrides the method and answers it itself. This is the only override today.
- Work that needs the signed bytes a consumer never sees. Regional proxying is the case: a delivery for a workspace or an installation this region does not own is forwarded to the other region, which replays those bytes. That one cannot be an incarnation override, because the routing belongs to a product and nothing under `posthog/ingress/` imports a product, so it arrives as a callable the product injects into the provider builder. It lands with the Slack and GitHub migrations; neither builder takes one yet.

The dispatcher then looks up the consumers for `(provider, app, event type)` and runs them in name order.
Order is not a contract.
The sort keeps logs and metrics stable, and stops a product from running first by registering earlier.
Anything that depends on another consumer's result belongs in one consumer.

## Adding a consumer

A product declares its consumers in `products/<product>/backend/webhook_consumers.py`, in a `WEBHOOK_CONSUMERS` sequence:

```python
WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="loops",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment", "pull_request", "push"}),
        handler=_run_loops,
    ),
)
```

The fields are:

- `name`, stable and unique per provider, and part of the dedup cache key.
- `provider` and `app`, which must match a `ProviderSpec` some incarnation declares.
- `event_types`, a subset of what that provider app declares.
- `handler`, a callable that takes one `WebhookDelivery` and returns nothing.

Registration is validated when the registry is built, and it fails closed.
A consumer that names a provider app nobody declares, reuses a name already taken for that provider, or registers for an event type the provider app does not declare raises `RegistryError`.
The alternative is worse: a consumer that looks registered and never runs.

The registry finds these modules through `posthog.products.load_product_modules("webhook_consumers")` on the first delivery, not at `django.setup()`.
Eager loading would put every product's webhook module on the startup import path, which `posthog/test/repo_invariants/test_startup_import_budget.py` exists to keep clear.
So keep the module itself cheap to import and defer the heavy imports into the handler, behind `# noqa: PLC0415`.

A handler runs synchronously inside the request.
A consumer that wants asynchronous work enqueues its own task and returns, which is what conversations and stamphog do.
A consumer that reads the database on this path wraps the read in `bounded_statement_timeout(ms, models=...)` from `posthog.ingress.dispatch.database`.
It installs `SET LOCAL statement_timeout` on each alias those models route to, so a slow query degrades to a missing lookup instead of costing the delivery.
Pass the models the read actually uses.
Opening an alias is itself unbounded, so reaching for one the read never touches can stall the delivery on connection setup before the cap is installed.

## Adding a provider

A provider is a `<provider>/` subpackage under `posthog/ingress/` with a `provider.py` in it.
Copy `github/` for the full shape, or `vapi/` for a small one.
It holds three things:

- `SPECS`, one `ProviderSpec` per app, naming the event types that app is subscribed to. The registry validates consumers against these.
- A `WebhookProvider` subclass with its `scheme()` from `verify/`, its `deliveries()` that reads the event type, delivery id and context off the request, and any status codes its protocol fixes.
- A `build_<provider>_provider(...)` function that returns it.

Add the module to `_INCARNATION_MODULES` in `posthog/ingress/providers.py` so the registry finds its specs and any core consumers.
Then register the URL with `build_webhook_view()`:

```python
opt_slash_path("webhooks/github", build_webhook_view(build_github_provider("posthog")))
```

Secrets and verifiers that belong to a product are passed into the builder rather than imported.
Slack's signing secret, the SNS message verifier and its topic allowlist, and the PandaDoc `enabled` predicate all arrive that way.
Nothing under `posthog/ingress/` imports a product.

Consumers a product does not own are registered by the incarnation itself, in a `CORE_CONSUMERS` tuple.
The GitHub installation lifecycle is the one case today: it keeps PostHog's own integration rows in step with GitHub.

### The DRF adapter path

An endpoint that genuinely needs DRF team scoping keeps its view and subclasses `posthog.auth.WebhookSignatureAuthentication`.
That base class still carries its own HMAC-SHA256 computation, so the two paths implement the same algorithm twice today.
Moving it onto the schemes in `posthog/ingress/verify/schemes.py` is its own PR.
Customer.io is the reference: it is team-scoped, its secret comes from that team's integration row, and it needs no fan-out, so `customerio/` contributes a scheme only and declares no spec.
Two cross-region lookups subclass the same base, each with its own header names and signed-input format.
Reach for this path only when the endpoint needs DRF's team scoping. Everything else goes through `build_webhook_view()`.

### The semgrep rule

`inbound-webhooks-go-through-ingress` lands in its own PR, as `.semgrep/rules/devex/inbound-webhooks-go-through-ingress.yaml`.
It fires on three shapes.
`hmac.compare_digest` in a module that also reads a known signature header.
`hmac` inside a function named like a signature verifier, in the verb form (`verify_signature`) or the predicate form (`signature_ok`, `_is_valid_signature`).
A vendor SDK call that verifies an inbound signature, such as `stripe.WebhookSignature.verify_header()`, because that shape carries no `hmac` for the first two to find.
`posthog/ingress/` is excluded because it is the sanctioned implementation.
`posthog/auth.py` sits in the ratchet below instead, until the DRF base class moves onto the ingress schemes.
Tests are excluded because a test builds a signature to send rather than verifying an inbound one.

The rest of the exclusion list is a ratchet.
Each entry is a verifier that predates ingress.
When you migrate an endpoint, delete its line from `paths.exclude` in the same PR, and check the change with `semgrep --config .semgrep/rules/devex/ .`.
A genuine exception carries `# nosemgrep: inbound-webhooks-go-through-ingress -- <reason>` on the line.

## Endpoints today

| Provider     | Path                                                    | App          | Consumers                                                                                                                                   | Product code                                                            |
| ------------ | ------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `github`     | `/webhooks/github`, `/webhooks/github/pr`               | `posthog`    | `installation_lifecycle`, `installation_repositories` (core), `conversations`, `loops`, `tasks_pr_backstop`, `tasks_pr_review`, `workflows` | `products/{tasks,conversations,workflows}/backend/webhook_consumers.py` |
| `github`     | `/webhooks/stamphog/github`                             | `stamphog`   | `stamphog_review`                                                                                                                           | `products/stamphog/backend/webhook_consumers.py`                        |
| `slack`      | `/api/conversations/v1/slack/events`                    | `supporthog` | `conversations_slack`                                                                                                                       | `products/conversations/backend/webhook_consumers.py`                   |
| `pandadoc`   | `/api/legal_documents/pandadoc`                         | `default`    | `legal_documents_signatures`                                                                                                                | `products/legal_documents/backend/webhook_consumers.py`                 |
| `vapi`       | `/api/user_interviews/vapi_webhook/`                    | `default`    | `user_interviews_vapi`                                                                                                                      | `products/user_interviews/backend/webhook_consumers.py`                 |
| `sns`        | `/webhooks/workflows/ses-events`                        | `default`    | `workflows_ses_events`                                                                                                                      | `products/workflows/backend/webhook_consumers.py`                       |
| `customerio` | `/api/projects/<team_id>/messaging/customerio/webhook/` | none         | none, it is the DRF adapter path                                                                                                            | `products/messaging/backend/api/customerio_webhook.py`                  |

Only the `stamphog` row is wired in the PR that adds this page.
The other rows land in their own PRs, one per owning team; until then those endpoints verify by hand, and the semgrep rule's ratchet list carries them when the rule lands.
The GitHub endpoints are declared in `posthog/urls.py`, as is the SES one.
The others are declared by the product that owns them.
See [`url-routing.md`](url-routing.md) for the routing rules those declarations follow, and [`github-webhooks.md`](github-webhooks.md) for the GitHub specifics.
The Vapi endpoint sits behind a per-IP throttle the product owns, because ingress has no throttle lane and the endpoint is public.

## Non-goals

Ingress stores no delivery log, runs no queue and no retry, lets no consumer decide the response, and promises no order.
["Non-goals" in the package README](../../posthog/ingress/README.md#non-goals) records each one and the reason for it.
Read that section before you propose any of them: each was a real proposal already.

## Why the budget and the statement cap exist

Past incidents on the GitHub webhook path were caused by unbounded query cost against a shared connection pool, not by the synchronous execution model.
The fixes that worked bounded the queries: [#83852](https://github.com/PostHog/posthog/pull/83852) scoped the run lookup to the installation's teams and put a statement timeout on the attribution lookup, and [#87779](https://github.com/PostHog/posthog/pull/87779) added the indexes it needed.
Ingress carries both controls as general ones, so the next endpoint gets them without rediscovering the incident.
