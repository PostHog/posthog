# Slack

Deliveries from the Slack Events API and from Slack's interactive components.

## Headers

- `X-Slack-Signature` carries the signature.
- `X-Slack-Request-Timestamp` carries the timestamp the signature covers.
- `X-Slack-Retry-Num` and `X-Slack-Retry-Reason` go into the delivery context, because they tell a consumer that Slack thinks a delivery failed.

## Signature scheme

HMAC-SHA256, hex encoded, with the prefix `v0=`.
The signed input is `v0:{timestamp}:{body}`, over the raw body of either endpoint.
The replay window accepts a timestamp up to 300 seconds old, which is Slack's own guidance, and up to 60 seconds in the future for clock skew.

## Delivery id and event type

For an event, the delivery id is the envelope's `event_id`.
The event type is the inner `event.type`, not the envelope's `type`, so a consumer registers for `message` rather than for `event_callback`.
An envelope that is not an `event_callback` becomes no delivery at all.

An interactive payload carries no id of its own, so its delivery id is `None` and dedup does not apply to it.
Its event type is the payload's own `type`, such as `block_actions`.
A consumer that needs idempotency there brings its own key.

Both contexts carry `slack_team_id`, which is `team_id` on an event envelope and `team.id` on an interactive payload.
An interactive delivery's context also carries `raw_payload`, the signed form field (see [Quirks](#quirks)).

## Apps and secrets

Two apps on one Slack app registration: `supporthog` for the Events API, and `supporthog_interactivity` for interactive components.
They are separate here because they are separate endpoints with separate payload types, so each one's consumers are validated against only the types its own endpoint receives.
The signing secret is the same for both, and it belongs to the product that owns the Slack app, so `build_slack_provider()` and `build_slack_interactivity_provider()` take it as a getter.
Nothing under `posthog/ingress/` reads it.

The `slack_app` product runs a second Slack app registration with its own signing secret, held as the `SLACK_APP_SIGNING_SECRET` instance setting.
Its endpoints answer Slack synchronously (a slash command, an interactivity ack, a cross-region workspace probe), so they keep their own views and verify through `build_slack_signature_scheme()` rather than through a provider.
`posthog.models.integration.validate_slack_request` is that call.

## Quirks

Slack's `url_verification` handshake wants the challenge echoed in the response body, which no consumer can do.
The incarnation answers it in `pre_dispatch_response()`, before dispatch.

Slack redelivers a delivery it got a non-2xx for, so `retry_status` is 502: a workspace ownership lookup that raised or hit its timeout, a forward to the region that owns the workspace that did not land, and a receipt write that raised must not be receipted, or the event is lost.
On the interactivity endpoint that also keeps a click visible: Slack shows the person who clicked a delivery error rather than nothing.

Both endpoints answer 403 when the signing secret is unset, which is `unconfigured_status`, not the package default of 500.
That is the status the hand-rolled views answered, and it keeps an instance that never connected SupportHog from turning every anonymous probe of a public URL into a server error.
`explains_rejections` is False with it, so neither rejection names its reason: which of the two a caller hit is an operator fact about the instance.
The other status codes are the defaults.

Interactive components are posted as a form with one `payload` field holding the JSON, so `SlackInteractivityProvider` overrides `parse()` and reads `request.POST`.
That read consumes the request stream under ASGI, which is safe only because the view verifies the raw body first.
Slack signs the form body rather than the field, and a parsed mapping cannot be serialized back into the signed bytes, so the field itself travels verbatim in the delivery context under `raw_payload`.
A consumer that keys idempotency on the signed bytes reads it there, and the payload stays exactly what Slack sent.

## Consumers

`conversations_slack`, on the `supporthog` app, for every event type the app is subscribed to.
`conversations_slack_interactivity`, on the `supporthog_interactivity` app, for the interactive payload types the app can receive.
Both declare `ownership`, so a delivery about a workspace the other region holds is forwarded there.
A lookup that does not answer, the bounded statement timeout included, forwards nothing and takes `retry_status`:
a lookup that never finished is no evidence that the other region owns the workspace, and the delivery carries the workspace's support messages.
It also sets `dedup=False`, because its receipt row is unique per Slack event id and already absorbs a redelivery.
A dedup mark would only add a way to lose one: a run that exits between the claim and the receipt commit leaves the mark behind with nothing durable written, and every redelivery then takes `retry_status` until Slack gives up.
See the [Endpoints table](../README.md#endpoints).
