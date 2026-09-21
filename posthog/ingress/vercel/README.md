# Vercel

Deliveries from the Vercel Marketplace integration: invoice events and deauthorization.

## Headers

- `x-vercel-signature` carries the signature.

Vercel sends no delivery header and no timestamp header.

## Signature scheme

HMAC-SHA1 over the raw body, hex encoded, with no prefix.
It is the only provider here that does not sign with SHA-256, which the `digest` field of `HmacSignature` carries.
There is no replay window, because there is no timestamp to check.

## Delivery id and event type

Vercel sends no delivery id, so dedup is skipped and the consumer carries its own idempotency.

The event type is the `type` field of the body, with one substitution.
Vercel names every invoice event `marketplace.invoice.<something>` and adds to the family over time, while the registry matches an exact event type.
The family is therefore registered under `marketplace.invoice` and the delivery carries that name.
The whole body travels as the payload, so the consumer reads the exact event name off `type` and hands it to the billing service.

Deauthorization keeps its own name, `integration-configuration.removed`.
Any other event type reaches no consumer and is receipted.

## Apps and secrets

One app, `marketplace`.
The secret is the Django setting `VERCEL_CLIENT_INTEGRATION_SECRET`.

## Quirks

Vercel registered this webhook URL against the secondary region, not the primary one.
It is the only provider here that does, and `receiving_region_domain` is what says so: deliveries arrive at the secondary region and a deauthorization for an installation the primary region holds is forwarded there.

A deauthorization for an installation neither region holds is still accepted.
A billing event never forwards, whichever region holds the installation, because the region that did not sell the plan cannot bill it.

A bad signature answers 401, which is what this endpoint answered before.
A missing secret answers 500 rather than that 401: an unset secret is an operator problem and not a verdict on the caller.

A delivery a consumer did not accept answers 500 rather than the 202 receipt.
Vercel does not redeliver after a non-2xx, so the 500 buys no retry; it keeps the status the endpoint answered before.

## Consumers

One consumer, `vercel_marketplace`, declared in `ee/api/vercel/webhook_consumers.py`.
`ee/` is not a product, so `posthog.ingress.dispatch.loading` names that module rather than discovering it.

The consumer routes an invoice event to the billing service and a deauthorization to the installation teardown, inside the request.
It declares the ownership lookup that decides the forward above.
See the [Endpoints table](../README.md#endpoints).
