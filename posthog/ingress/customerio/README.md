# Customer.io

The signature scheme for the Customer.io reporting webhook, which stays on the DRF adapter path.

## Headers

- `x-cio-signature` carries the signature.
- `x-cio-timestamp` carries the timestamp the signature covers.

## Signature scheme

HMAC-SHA256, hex encoded, with no prefix.
The signed input is `v0:{timestamp}:{body}`.
The replay window is the default one: 300 seconds old at most, and 300 seconds into the future at most.

## Delivery id and event type

Neither exists here.
This incarnation contributes a scheme only, so it reads no deliveries off a request, and dedup does not apply.
The DRF view reads the event out of the body itself.

## Apps and secrets

No app and no `ProviderSpec`, because nothing dispatches here.
The secret is per team: it comes from that team's messaging integration row rather than from a setting, which is why the endpoint keeps DRF's team scoping.

## Quirks

This is the DRF adapter path.
`posthog.auth.WebhookSignatureAuthentication` does the verifying, and the view answers 200 for an event it does not handle.
That class still carries its own HMAC-SHA256 computation rather than the scheme described above, so the scheme here documents the shape without being on the request path yet.
Moving the class onto the ingress schemes is its own PR.
Reach for this path only when an endpoint genuinely needs DRF's team scoping.
Everything else goes through `build_webhook_view()`.

## Consumers

None.
This is the DRF adapter path, with no dispatcher.
The endpoint is `/api/projects/<team_id>/messaging/customerio/webhook/`, served by `products/messaging/backend/api/customerio_webhook.py`.
