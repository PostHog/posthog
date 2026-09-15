# Vapi

Deliveries from the Vapi voice agent.

## Headers

- `X-Vapi-Signature` carries the signature.

Vapi sends no delivery header and no timestamp header.

## Signature scheme

HMAC-SHA256 over the raw body, hex encoded, with no prefix.
There is no replay window, because there is no timestamp to check.
A signature that is not 64 lowercase hex characters is rejected before the HMAC runs, which keeps a casual probe off the digest path.

## Delivery id and event type

Vapi sends no delivery id, so dedup is skipped.
The call id is the only stable id in the payload, and it repeats across the status update and the end-of-call report.
It therefore cannot key dedup: a mark set by the first message would swallow the second.
The call id goes into the delivery context as `call_id`, and the consumer stays idempotent on it.
The event type is `message.type`.

## Apps and secrets

One app, `default`.
The secret is the Django setting `VAPI_WEBHOOK_SECRET`.

## Quirks

A bad signature answers 401 and an unconfigured instance answers 503.
The public interview surface already relies on both codes.

## Consumers

No product registers a Vapi consumer yet.
The user interviews endpoint moves to ingress in its own PR.
See the [Endpoints table](../README.md#endpoints).
