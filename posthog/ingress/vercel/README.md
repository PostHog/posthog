# Vercel

Deliveries from the Vercel Marketplace integration: invoice lifecycle events and the deauthorization event.

## Headers

- `x-vercel-signature` carries the signature ([Vercel request headers](https://vercel.com/docs/headers/request-headers#x-vercel-signature)).

Vercel sends no delivery header and no timestamp header. The delivery id is in the body.

## Signature scheme

HMAC-SHA1 over the raw body, hex encoded, with no prefix.
The key is the integration's Client Secret, which Vercel also calls the Integration Secret ([Vercel request headers](https://vercel.com/docs/headers/request-headers#x-vercel-signature)).
SHA-1 is Vercel's choice, not one made here; every other provider in this package signs with SHA-256.
There is no replay window, because there is no timestamp to check.
Vercel ships no Python verifier, so the shared `HmacSignature` does the check rather than a vendor SDK.

## Delivery id and event type

Vercel sends a delivery id as the body's `id` field ([Vercel webhooks](https://vercel.com/docs/webhooks)).
It is not used: `delivery_id` is `None`, so dedup is off.
Turning dedup on changes which redeliveries reach the consumer, and a mark that outlives a run can drop a delivery, so it gets its own change rather than riding along with a transport swap.
The consumer carries its own idempotency in the meantime, as it did before.

The event type is the body's `type`.
Vercel names every invoice event `marketplace.invoice.<something>` and adds to the family over time, while the registry matches an exact event type.
So the family is registered under the prefix `marketplace.invoice`, the whole envelope travels as the delivery payload, and the consumer reads the exact name off `type`.
`integration-configuration.removed` is passed through unchanged.

## Apps and secrets

One app, `marketplace`.
The secret is the Django setting `VERCEL_CLIENT_INTEGRATION_SECRET`.

## Quirks

The marketplace App holds one webhook URL, registered against the secondary region (US), so `receiving_region_domain()` is overridden and the forward runs to the primary region (EU).
Vercel is the only provider here that does that.

Both event families declare ownership, because both are processed by the region that holds the installation: only there does the billing manager find the `Organization` a billing call needs, and only there is there an installation to delete.
The ownership lookup reads `OrganizationIntegration` by kind and integration id, which is a scan of a small table rather than an indexed point lookup, so it runs under `bounded_statement_timeout`.

A bad signature answers 401, and so does a missing secret.
Both are what the endpoint answered before this moved onto ingress, and Vercel's integration is built against them.
A missing secret also reaches error tracking (`reports_unconfigured`), because the 401 hides it from anyone reading status codes while every invoice event is refused.

A delivery ingress cannot vouch for answers 500 rather than the 202 receipt: a consumer that raised, a forward that failed or answered non-2xx, or an ownership lookup that did not answer.
Vercel does not publish a retry policy, so whether that buys a redelivery is unknown.
The status is right either way, because the work did not run, and it is what the endpoint answered before.

An event for an installation **no** region holds is receipted with 202, and that is a deliberate change from the 404 the endpoint used to answer.
By the time the primary region has looked, both regions have looked, and no later attempt can find an installation that does not exist, so a failure status reports a failure that will never resolve.
The miss is still reported: the primary region, which looks last, logs `vercel_webhook_unknown_config` or `vercel_webhook_deauthorize_unknown_config` at warning level.
The secondary region logs the same at info, because there a local miss is what the forward is for, and a warning per delivery would fire for every event of every installation the other region holds.

## Consumers

One consumer, `vercel_marketplace`, declared in `ee/api/vercel/webhook_consumers.py` and named in `posthog/ingress/dispatch/loading.py`, because `ee/` is not a product and nothing discovers it.
A build without an `ee/` tree skips it and has no Vercel endpoint either.

The handler runs inside the request. It hands a billing event to the billing service, which waits up to 30 seconds, and a deauthorization to `VercelIntegration.delete_installation`.
That 30 seconds is why `forward_timeout_seconds` is 35: a shorter deadline would make the receiving region give up on an invoice the other region is still processing.
