# Vercel

Deliveries from the Vercel Marketplace integration: invoice events and deauthorization.

## Headers

- `x-vercel-signature` carries the signature.

Vercel sends no delivery header and no timestamp header. The delivery id is a body field, not a header.

## Signature scheme

HMAC-SHA1 over the raw body, hex encoded, with no prefix.
It is the only provider here that does not sign with SHA-256, which the `digest` field of `HmacSignature` carries.
There is no replay window, because there is no timestamp to check.

## Delivery id and event type

Vercel does send a delivery id: every body is `{"id", "type", "createdAt", "payload", "region"}`, and [its field table](https://vercel.com/docs/webhooks) calls `id` the webhook delivery id.

This incarnation passes `delivery_id=None` all the same, so dedup is skipped and the consumer carries its own idempotency, which is what the endpoint did before.
Keying dedup on that id changes which redeliveries reach the consumer, and a mark that outlives a failed run can drop one for 24 hours. That is a behavior change on its own, not part of swapping the transport, so it gets its own PR.

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

The forward runs under a 10 second timeout, which is what the cross-region proxy it replaces allowed for the same hop.

A deauthorization for an installation neither region holds is still accepted.
A billing event never forwards. One for a configuration this region does not hold is reported to error tracking and receipted, which is what the old endpoint did apart from the status: it reported the same thing and answered 404. It was never forwarded before either.

A bad signature answers 401, and so does a missing secret.
The 401 on a missing secret is inherited, not chosen: the old verifier could not tell the caller apart from the operator, and a migration that only changes the transport keeps the status the endpoint answered.
The package default would be 500. Because that 401 hides an operator problem from anyone reading status codes, this is one of the providers that sets `reports_unconfigured`, so a missing secret reaches error tracking as it did before.

A delivery a consumer did not accept answers 500 rather than the 202 receipt.
Vercel publishes no retry policy, so whether that buys a redelivery is unknown. The status is right either way: the work did not run, and it is what the endpoint answered before.

## Consumers

One consumer, `vercel_marketplace`, declared in `ee/api/vercel/webhook_consumers.py`.
`ee/` is not a product, so `posthog.ingress.dispatch.loading` names that module rather than discovering it.

The consumer routes an invoice event to the billing service and a deauthorization to the installation teardown, inside the request.
It declares the ownership lookup that decides the forward above.
See the [Endpoints table](../README.md#endpoints).
