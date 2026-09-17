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

Slack redelivers a delivery it got a non-2xx for, so `retry_status` is 502: a workspace ownership lookup that raised or hit its timeout, a forward to the region that owns the workspace that did not land, and a receipt write that raised must not be receipted, or the event is lost.
The other status codes are the defaults.

## Consumers

`conversations_slack`, on the `supporthog` app, for every event type the app is subscribed to.
It declares `ownership`, so a delivery about a workspace the other region holds is forwarded there.
A lookup that does not answer, the bounded statement timeout included, forwards nothing and takes `retry_status`:
a lookup that never finished is no evidence that the other region owns the workspace, and the delivery carries the workspace's support messages.
See the [Endpoints table](../README.md#endpoints).
