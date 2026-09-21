# Linear

Deliveries from the Linear OAuth application webhook.

## Headers

- `Linear-Signature` carries the signature.
- `Linear-Delivery` carries a UUID v4 for each delivery.
- `Linear-Event` carries the entity type, such as `Issue` or `Comment`.
- `Linear-Timestamp` carries a timestamp in milliseconds.

## Signature scheme

Linear signs the raw body with HMAC-SHA256, hex encoded, with no prefix.
The signing key is the OAuth application's webhook signing secret.

## Delivery id and event type

Both values come from headers.
A request without `Linear-Delivery` has no delivery id and skips dedup.

The payload's `organizationId` goes into the delivery context as `organization_id`.
It is the Linear workspace id, which `Integration.integration_id` stores for a `linear` integration through `id_path="data.viewer.organization.id"` in `posthog/models/integration/oauth.py`.
A consumer resolves the tenant from this value.

## Apps and secrets

One app, `default`.
The secret is the `LINEAR_WEBHOOK_SECRET` instance setting, so an operator can rotate it without a deploy.

Configure the webhook URL and resource types on the Linear OAuth application, then copy its signing secret to `LINEAR_WEBHOOK_SECRET`.

## Quirks

There is no replay window.
Linear's recommended replay check reads `webhookTimestamp` from the body in milliseconds, while the shared scheme's window expects a header timestamp in seconds.
The replay risk is low because the body is signed and `Linear-Delivery` deduplicates a replayed delivery.

The provider does not set `retry_status` because Linear does not redeliver on a non-2xx response.
A non-2xx response would only lose the event.

## Consumers

The `error_tracking_linear_external_references` consumer is declared in `products/error_tracking/backend/webhook_consumers.py`.
