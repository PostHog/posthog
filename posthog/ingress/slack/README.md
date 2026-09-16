# Slack

Deliveries from the Slack Events API.

## Headers

- `X-Slack-Signature` carries the signature.
- `X-Slack-Request-Timestamp` carries the timestamp the signature covers.
- `X-Slack-Retry-Num` and `X-Slack-Retry-Reason` go into the delivery context, because they tell a consumer that Slack thinks a delivery failed.

## Signature scheme

HMAC-SHA256, hex encoded, with the prefix `v0=`.
The signed input is `v0:{timestamp}:{body}`.
The replay window accepts a timestamp up to 300 seconds old, which is Slack's own guidance, and up to 60 seconds in the future for clock skew.

## Delivery id and event type

The delivery id is the envelope's `event_id`.
The event type is the inner `event.type`, not the envelope's `type`, so a consumer registers for `message` rather than for `event_callback`.
An envelope that is not an `event_callback` becomes no delivery at all.
The context also carries `slack_team_id`.

## Apps and secrets

One app, `supporthog`.
The signing secret belongs to the product that owns the Slack app, so `build_slack_provider()` takes it as a getter.
Nothing under `posthog/ingress/` reads it.

## Quirks

Slack's `url_verification` handshake wants the challenge echoed in the response body, which no consumer can do.
The incarnation answers it in `pre_dispatch_response()`, before dispatch.
The status codes are the defaults.

## Consumers

No product registers a Slack consumer yet.
The conversations Slack endpoint moves to ingress in its own PR.
See the [Endpoints table](../README.md#endpoints).
