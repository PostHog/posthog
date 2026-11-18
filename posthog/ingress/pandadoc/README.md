# PandaDoc

Deliveries from PandaDoc document events.

## Headers

- `X-PandaDoc-Signature` carries the signature.
- The `signature` query parameter is the fallback, read only when that header is absent.

Presence decides, not truthiness.
An empty header is a signature that fails, never a reason to look for a query parameter the caller did not sign with.

## Signature scheme

HMAC-SHA256 over the raw body, hex encoded, with no prefix.
PandaDoc sends no timestamp, so there is no replay window.

## Delivery id and event type

PandaDoc sends no delivery id, so dedup is skipped and a consumer carries its own idempotency.
The event type is the `event` field of each event object in the body.

## Apps and secrets

One app, `default`.
The secret is the Django setting `PANDADOC_WEBHOOK_SECRET`.

## Quirks

PandaDoc batches several events into one body, so one request becomes one delivery per event, and all of them draw from the one request budget.
A bad signature answers 404 instead of 403, so a prober cannot tell a wrong secret from an unknown route.
A missing secret answers 404 too, and neither rejection carries a body, because the reason would hand back what the status code withholds.

`retry_status` is 500, which is what this endpoint answered before it moved here, and PandaDoc redelivers after a non-2xx.
So a consumer that raised, a forward that never landed, and a consumer the request budget skipped all cost the request its receipt, and the delivery comes back rather than being lost.
The 500 is reachable only after a valid signature, so it withholds the endpoint's existence exactly as the two 404s above do.
A redelivery replays the whole batched body against the consumer, which is why the consumer carries its own idempotency.

## Consumers

`legal_documents_signatures`, declared in `products/legal_documents/backend/webhook_consumers.py`.
It records signatures for the document signing flow.
See the [Endpoints table](../README.md#endpoints).
