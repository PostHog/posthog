# Linear

Deliveries from the PostHog Linear OAuth App.

## Headers

- `Linear-Signature` carries the signature.
- `Linear-Delivery` carries the delivery id.
- `Linear-Event` carries the event type.

Linear also sends `Linear-Timestamp`.
It is not covered by the signature, so nothing reads it.

## Signature scheme

HMAC-SHA256 over the raw body, hex encoded, with no prefix.
A signature that is not 64 lowercase hex characters is refused before the HMAC runs.

The replay window is read from `webhookTimestamp` in the body, a UNIX timestamp in milliseconds.
A body sent more than 60 seconds before or after it arrives answers 400, which is the window Linear recommends.
The check runs in `deliveries`, after verification, because the scheme only reads headers before the body.
Linear's own SDK verifier (`packages/sdk/src/webhooks/client.ts` in `linear/linear`) applies the same 60-second window to the signed `webhookTimestamp`.
So a redelivery carries a new timestamp, or no receiver built on that SDK could accept one.

## Delivery id and event type

Both come from headers, never from the body.
A request without `Linear-Delivery` gets no delivery id and skips dedup.
The payload's `organizationId` goes into the delivery context as `organization_id`.
It is the Linear workspace id, which is also the `integration_id` of a `linear` integration row.

## Apps and secrets

One app, `posthog`, the Linear OAuth App that the `linear` integration connects through.
Its secret is the signing secret from the App's webhook settings in Linear, read as `LINEAR_APP_WEBHOOK_SECRET`.
It is a plain env var on the Django pods, wired from `posthog-django-shared-secrets` the way `VERCEL_CLIENT_INTEGRATION_SECRET` is.
It stays off the credentials service, because every deployment that holds a caller key can read any entry there, and an inbound signing secret must not be that widely readable.

The App's webhook settings subscribe to the `Issue` resource type.
Linear creates the webhook for a workspace when the workspace authorizes the App, so a workspace that authorized it before the webhook settings existed gets deliveries only after it connects again.

One Linear App serves both regions.
Its webhook URL names the primary region, `https://eu.posthog.com/webhooks/linear`, so every delivery arrives there first.

## Quirks

Success answers 200, not the default 202, because Linear counts any other status as a failed delivery.
Linear retries a failed delivery after 1 minute, 1 hour and 6 hours, and it can disable a webhook that keeps failing.
`retry_status` is 500, so a consumer that raised or that the request budget skipped asks for that retry.
A missing secret answers 403 rather than 500, because a self-hosted deployment may never set up the Linear App.
Rejections carry an empty body, so a caller cannot tell a missing secret from a bad signature.

## Consumers

None. The endpoint verifies each delivery and answers 200, and nothing acts on it.
See the [Endpoints table](../README.md#endpoints).
