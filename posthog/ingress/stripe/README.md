# Stripe

The signature scheme for the Stripe partner provisioning API, which stays on the DRF adapter path.

## Headers

- `stripe-signature` carries the timestamp and every signature in one value: `t=<timestamp>,v1=<hex>`.
- `api-version` carries the protocol version. The views check it themselves; it is not part of the signature.

## Signature scheme

HMAC-SHA256, hex encoded, with no prefix.
The signed input is `{timestamp}.{body}`, where the timestamp is the one the header carries.
The replay window is 300 seconds old at most.
A timestamp in the future passes, which is what Stripe's own verifier does, so a sender whose clock runs ahead keeps working.

## Delivery id and event type

Neither exists here.
This incarnation contributes a scheme only, so it reads no deliveries off a request, and dedup does not apply.
Each endpoint is its own operation, named by its URL.

## Apps and secrets

No app and no `ProviderSpec`, because nothing dispatches here.
The secret is instance-wide: `STRIPE_SIGNING_SECRET`.
A request that arrives while it is unset answers 500, because an unset secret is an operator problem rather than a caller one.

## Quirks

The header can carry several `v1` entries.
While the secret is rotating, the sender signs each request with the old secret and the new one, so verification passes when any entry matches.

This is the DRF adapter path, and a different one from Customer.io: the caller is `ee/partners/stripe/api/provisioning/signature.py` rather than `posthog.auth.WebhookSignatureAuthentication`.
The endpoints answer a flat error envelope the partner spec fixes, and they run the signature check and the API-Version check in an order the spec fixes too, so the module keeps `verify_stripe_signature` and delegates only the verification itself.

The spec also defines a preferred `Stripe-Signature-V2` scheme, an EdDSA-signed JWT verified against keys fetched from the orchestrator.
When Stripe moves off legacy HMAC, that verification belongs here as a second scheme, next to `StripeSignature`.

## Consumers

None.
This is the DRF adapter path, with no dispatcher.
The endpoints sit under `/api/partners/stripe/`, served by `ee/partners/stripe/api/provisioning/views.py`.
