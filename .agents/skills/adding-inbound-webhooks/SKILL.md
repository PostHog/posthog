---
name: adding-inbound-webhooks
description: >
  Use when adding a webhook endpoint for a third party that sends to PostHog, adding an inbound webhook consumer for a provider that already has an endpoint, or migrating a hand-rolled hmac verifier that the `inbound-webhooks-go-through-ingress` semgrep rule flags.
  Covers the two jobs separately: a consumer in `products/<product>/backend/webhook_consumers.py`, and a provider incarnation under `posthog/ingress/<provider>/` wired with `build_webhook_view()`.
  Carries the rules that are easy to get wrong: a consumer name is a dedup cache key, event types must be declared by the provider app or the registry raises, and the module stays cheap to import.
  Trigger terms: add a webhook, webhook consumer, inbound webhook, hand-rolled hmac, inbound-webhooks-go-through-ingress.
---

# Adding an inbound webhook

Every webhook a third party sends to PostHog goes through `posthog/ingress/`.
Read [posthog/ingress/README.md](../../../posthog/ingress/README.md) for the transport contract and the package reference.
This skill is the decision tree and the checklists.

Which job are you doing?

- The provider already has an endpoint (see the Endpoints table in `posthog/ingress/README.md`) and you want to react to its events: **add a consumer**.
- No endpoint exists for this third party, or the semgrep rule flagged a hand-rolled verifier: **add a provider**, then add its consumer.
- Outbound call to a vendor API, which is the other direction: `/routing-outbound-api-calls`.

## Add a consumer

A product declares its consumers in `products/<product>/backend/webhook_consumers.py`, in a `WEBHOOK_CONSUMERS` sequence of `WebhookConsumer` values from `posthog.ingress.contracts`.
`products/stamphog/backend/webhook_consumers.py` is the smallest complete example.

```python
WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="stamphog_review",
        provider="github",
        app="stamphog",
        event_types=frozenset({"pull_request"}),
        handler=_run_review,
    ),
)
```

Rules that decide whether this works:

- `name` is unique per provider and is part of the dedup cache key. **Treat it as fixed once it ships**: renaming one lets a redelivery run the consumer a second time.
- `provider` and `app` must match a `ProviderSpec` some incarnation declares, and `event_types` must be a subset of what that app declares. Anything else raises `RegistryError` when the registry is built, rather than sitting there looking registered and never running.
- `handler` takes one `WebhookDelivery` and returns nothing. Its return value is ignored and never decides the HTTP status. A handler that raises does cost the request its receipt when the provider sets `retry_status`, which is how a consumer whose durable record is written inside the handler gets the delivery again.
- Keep the module cheap to import. The registry imports it on the first delivery through `load_product_modules("webhook_consumers")`, so defer heavy imports into the handler behind `# noqa: PLC0415` with a reason.
- The handler runs synchronously inside the request. Enqueue a task for real work, the way stamphog and conversations do.
- A handler that reads the database wraps the read in `bounded_statement_timeout(ms, models=...)` from `posthog.ingress.dispatch.database`, passing only the models the read actually uses. Opening an alias is itself unbounded, so naming one the read never touches can stall the delivery on connection setup.
- An import-linter contract (`webhook consumers must only import facade`) holds the module to its own product's `facade/`. Reach product internals through the facade.
- A consumer whose resources are split across regions declares `ownership=`, pointing at a facade function that returns a `DeliveryOwnership`. Ingress forwards the signed request when the answer is `ELSEWHERE`, and dispatches locally either way. The lookup runs inside the request, so bound it with `bounded_statement_timeout(ms, models=...)`.

Tests: extend the product's existing webhook test module rather than starting a parallel one.
`products/stamphog/backend/tests/test_webhook_consumers.py` is the shape: drive the real view with a signed `RequestFactory` request and assert the enqueue, plus the event type the app does not register, the bad signature, the unparseable body, the non-POST, and the missing secret.
Reset the process-cached registry and the dedup cache between tests with `reset_consumer_registry()` and `cache.clear()`.

## Add a provider

Create `posthog/ingress/<provider>/` with an `__init__.py` and a `provider.py`.
Copy `github/` for the full shape, or `vapi/` for a small one.
`provider.py` holds three things:

- `SPECS`, one `ProviderSpec` per app, naming the event types that app is subscribed to. The registry validates consumers against these.
- A `WebhookProvider` subclass with `scheme()` (from `posthog/ingress/verify/`), `deliveries(request, payload, facts)` (how to read the event type, delivery id and context off the verified request), and any status codes the provider's protocol fixes. Defaults are 403 on a bad signature, 500 when unconfigured, 202 on success.
  - `verify(request)` answers a `Verification`: the outcome, plus `facts`, whatever the scheme proved on the way. A scheme that validates a signed token puts its verified claims there and `deliveries` cross-checks the body against them; an HMAC scheme leaves it empty and `deliveries` ignores it.
  - `parse(request)` decodes the body, and defaults to JSON. Override it for a provider that posts a form, and raise `InvalidPayload` for a body it cannot read. Verification runs first and must, because reading `request.POST` consumes the request stream under ASGI.
  - `throttle_class` names a DRF throttle from `posthog.rate_limit`, run in front of verification. Set one when the endpoint is public and its verification is expensive, such as a JWT signing-key lookup.
  - `retry_status` is the status answered instead of the receipt when ingress cannot vouch that the delivery was accepted: the forward to the owning region failed, a consumer raised, or the budget skipped a consumer. Set it when the provider redelivers on a non-2xx, and leave it `None` when it does not, because the non-2xx then only loses the delivery. A retry replays the delivery against every consumer on the endpoint, and dedup is what stops the ones that already accepted it from running twice.
- A `build_<provider>_provider(...)` function returning it. Secrets and verifiers a product owns are **passed into this builder**, never imported: nothing under `posthog/ingress/` may import a product.

### Picking a scheme

Three exist. Configure one; do not write a fourth without reading [the Schemes section of the package README](../../../posthog/ingress/README.md#schemes).

- `HmacSha256` (`verify/schemes.py`) — a shared secret over the raw body. Covers hex or base64, an optional prefix, and the `v0:{timestamp}:{body}` input with a replay window that Slack and Customer.io sign. GitHub, Slack, PandaDoc, Vapi and Customer.io all use it.
- `SnsSignature` (`verify/schemes.py`) — the AWS SNS envelope check plus a topic-ARN allowlist. The RSA work stays with a caller-supplied verifier.
- `BearerJwt` (`verify/jwt.py`) — a `Bearer` token signed as a JWT, checked against the issuer's published JWKS. Its `facts` are the verified claims. The incarnation supplies the JWKS URI, the audience and the issuer allowlist as callables, and caches any discovery it does to find the URI. An endpoint on this scheme sets `throttle_class`, because an unsigned request costs a signing-key lookup.

Then:

1. Add the module path to `_INCARNATION_MODULES` in `posthog/ingress/providers.py`, or the registry never sees its specs or core consumers.
2. Wire the URL with `build_webhook_view()` where the App registration lives. The owner of the third-party App owns the route: a product that registered the App declares `urlpatterns` in its own `products/<product>/backend/routes.py`, for example `opt_slash_path("webhooks/<product>/<provider>", build_webhook_view(build_<provider>_provider()))`. The path must start with `webhooks/<product>/` or `api/<product>/`, or the URL conf fails to load. Only an App several products consume stays in `posthog/urls.py`, which today is the customer-facing GitHub App alone. See [docs/internal/url-routing.md](../../../docs/internal/url-routing.md).
3. Write `posthog/ingress/<provider>/README.md` with the fixed sections, in this order: headers, signature scheme, delivery id and event type, apps and secrets, quirks, consumers. `posthog/ingress/test/test_provider_readme_sections.py` fails on a provider folder without one, and on a README with different or reordered headings.
4. Add the provider's signature header name to the `$HEADER` regex in `.semgrep/rules/devex/inbound-webhooks-go-through-ingress.yaml`, plus a fixture case in the `.py` beside it. The header names are spelled out rather than matched generically because a generic header pattern makes semgrep time out on a large module, which drops that file from the scan without failing it.
5. Delete the migrated endpoint's line from `paths.exclude` in the same rule. That list is a ratchet of verifiers that predate ingress, and the migrating PR removes its own entry.
6. Preserve the endpoint's externally observable behavior. Existing tests are the contract: move or extend them, do not drop assertions.

### The DRF adapter path

An endpoint that genuinely needs DRF team scoping keeps its view and subclasses `posthog.auth.WebhookSignatureAuthentication`, which computes and compares through `posthog/ingress/verify/schemes.py`.
Customer.io is the reference: team-scoped, secret from that team's integration row, no fan-out, so `customerio/` contributes a scheme only and declares no spec.
Everything else goes through `build_webhook_view()`.

## Non-goals

Ingress stores no delivery log, runs no queue, retry or dead letter of its own, lets no consumer decide the response, and promises no consumer order.
It does answer `retry_status` when it cannot vouch that a delivery was accepted, which asks the provider's retry to run rather than adding one here.
Each was a real proposal already; ["Non-goals" in the package README](../../../posthog/ingress/README.md#non-goals) records the reason for each one, so read it before proposing any of them again.

## Verify

```sh
semgrep --config .semgrep/rules/devex/ .          # the ratchet entry is really gone
semgrep --test .semgrep/                          # only if you changed the rule itself
lint-imports                                      # the webhook_consumers contract
hogli test products/<product>/backend/tests/test_webhook_consumers.py
hogli test posthog/ingress/test/
ruff check --fix <touched files> && ruff format <touched files>
```
