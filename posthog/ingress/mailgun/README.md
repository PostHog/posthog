# Mailgun

Deliveries from Mailgun routes, which forward a mail message to PostHog.

## Headers

None.
Mailgun signs a route delivery in the form body, not in a header: the fields are `signature`, `timestamp` and `token`.
The incarnation hands those three to the shared HMAC scheme as if they were headers, because the scheme reads a mapping and does not care where the caller found it.

## Signature scheme

HMAC-SHA256 over `timestamp + token`, hex encoded, with no prefix.
The signature does not bind the message, because Mailgun signs those two fields and nothing else.
A captured pair therefore authenticates any body until the replay window closes, which is why the window is not optional: the scheme refuses a timestamp more than 5 minutes old, and one more than 5 minutes in the future.

`verify` reads `request.POST`, never `request.body`.
A multipart body is consumed by the form parser, which leaves no raw bytes for a later read.
`parse` then reads the same cached form again, so the second read costs nothing.

## Delivery id and event type

The delivery id is the `token` field.
Mailgun mints a fresh token per delivery, so dedup is on.

A route carries a message rather than an event, so there is no event field to read.
Each app has one fixed event type: `message_received` for `inbound` and `capture`, and `message_sent` for `outbound`.

## Apps and secrets

Three apps, one per route:

- `inbound` — mail a customer sent to a PostHog inbox address.
- `outbound` — mail a customer's own agent sent, captured by a second route.
- `capture` — one catch-all route that carries both, where the recipient local part is the only thing that tells them apart. Its event type is the inbound one, because the app types the delivery and the split is the consumer's to make.

All three take a `signing_key_getter` from the builder.
The key is per Mailgun account rather than per route, so a caller that mounts both endpoints passes the same getter twice.
The getter is injected because the setting that holds the key belongs to the product that registered the account, and nothing under `posthog/ingress/` imports a product.
Keep the getter cheap or cached: the scheme calls it on every request, before it looks at the signature, so an unsigned probe reaches it too.

## Quirks

Mailgun never posts JSON to a route.
The payload is the form flattened to a mapping of field name to string, plus one reserved key, `_files`, which holds the uploaded attachments by field name.

A consumer must read a file inside the request.
An `UploadedFile` is backed by the request stream or by a temporary file, so it does not survive the response and cannot be handed to a task as it is.
A consumer that wants the attachment later stores it first, then passes the stored reference.

The file count is capped at 20, the cap the conversations inbound view applied before it moved here.
The cap bounds what a consumer iterates, not what the request costs: the form parser reads and spools every part first, and Django's `DATA_UPLOAD_MAX_NUMBER_FILES` is what bounds that.

The whole body is parsed before the signature is checked, because the signature lives in the form.
An unsigned caller therefore buys a full multipart parse for its 403, which is a reason to set `throttle_class` on the provider when an endpoint mounts it.

A forwarded delivery crosses as a rebuilt form rather than as the raw bytes, because the form read leaves none.
[Regional forwarding](../README.md#regional-forwarding) carries the rule, and a region-split consumer declares `ownership` as it would on any other provider.

Mailgun's event webhooks (delivered, failed, opened) are a different payload shape, with the event name in the form.
They would be a third app, added when a product needs one.

## Consumers

Conversations registers one consumer per app, in `products/conversations/backend/webhook_consumers.py`:

- `conversations_email_inbound` — opens or continues a support ticket, or ingests a customer email thread.
- `conversations_email_outbound` — records mail a customer's own agent sent.
- `conversations_email_capture` — reads the recipient local part and runs whichever of the two the message is.

All three declare `ownership`, because a team's email channel lives in one region.
The inbound apps resolve the channel by the `team-<token>@` inbound address, the outbound app by the sending address on an active customer-communication channel.
An address this region does not hold answers `ELSEWHERE`, so the delivery reaches the region that does.
The outbound app is the exception when the lookup does not finish: the same sending address can be active in both regions, so it raises instead of answering `ELSEWHERE`, because a forward on an unfinished lookup reaches a region that ingests the capture at once.

`retry_status` is 502 on this provider, so a forward that never landed and a consumer that raised both cost the request its receipt and Mailgun redelivers.
See the [Endpoints table](../README.md#endpoints).
