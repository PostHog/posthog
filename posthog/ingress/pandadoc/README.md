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

## Consumers

No product registers a PandaDoc consumer yet.
The legal documents endpoint moves to ingress in its own PR.
See the [Endpoints table](../README.md#endpoints).
