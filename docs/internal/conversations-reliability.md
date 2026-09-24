# Conversations delivery reliability

How Conversations stores inbound callbacks and outbound delivery state.
This is the control-plane contract for Slack, email, and the widget.
It is not a product-facing runbook.

## Boundaries

**PostgreSQL is authoritative.**
Accepted inbound work, idempotency keys, leases, retry schedules, provider correlation, delivery state, and manual redrive live in Postgres.
A 2xx to Slack (or a returned widget message id) means a Postgres row committed, not that a Celery task ran.

**Redis is optional.**
It may be a fast-path lock or cache.
Losing Redis must not lose work or permanently suppress a callback.

**Celery is a wake-up hint.**
`on_commit` dispatch is the low-latency path.
A periodic Postgres sweeper is the durability backstop when the broker drops the hint.

**ClickHouse is derived history only.**
It never controls acknowledgement, retries, or delivery state.
Live operations use Postgres and Prometheus.
ClickHouse may receive sanitized batch-level lifecycle metrics, not payloads, leases, or provider secrets.

**Kafka / WarpStream is not in this design yet.**
Do not dual-write Postgres and Kafka in one request.
Revisit only when a region sustains the triggers in the program plan: claim-query p95 above one second after doubling workers, ingress above a few hundred durable rows per second that consumes material primary write capacity, a second consumer that needs ordered replay past Postgres retention, or the need to ack Slack while the owning Postgres region is down.
Until then, scale indexed sweepers.
If Kafka is added later, it is a wake-up relay from the Postgres outbox, not a second source of truth.
Widget writes stay synchronous in Postgres because the API must return ticket and message ids.

## Unread ticket count

The app fetches the unread ticket count when support is enabled and polls every 5 seconds while the browser tab is visible.
Ticket actions can trigger an immediate refresh.
Unrelated updates to the current team do not reset the count or trigger another request.
Changing teams or toggling support resets the count and restarts polling when support is enabled.
Failed requests retain the previous count and increase the polling interval.

## Inbound receipts (`ConversationInboundEvent`)

One row per accepted provider callback, keyed by `(team, source, source_id)`.
`team` is the canonical root team used for scoping and deduplication.
Required `provider_account_id` preserves the Slack workspace or other provider account so workers can resolve the environment-owned configuration after payload cleanup.

- Slack Events API uses Slack `event_id`.
- Slack interactivity uses `trigger_id` plus action/container identity (signed-body hash as fallback).
- Mailgun delivery callbacks can reuse this table later, with Mailgun's event id as `source_id`.

The row holds bounded Slack JSON (`payload`, max 256 KiB), the latest provider retry metadata, lease and fencing fields, attempt count, due time, bounded error fields, and optional ticket/comment UUIDs.
Those UUIDs are not foreign keys: they must not take locks on `posthog_comment` or `posthog_conversations_ticket`.

Retention:

- If a callback exceeds the payload limit, ingress persists the receipt without `payload`, records `payload_too_large`, and acknowledges it. Ingress must catch `InboundPayloadTooLargeError` to distinguish this case from an unexpected failure.
- After a row is terminal, null `payload` after 24 hours.
- Keep the compact `(team, source, source_id)` tombstone for 30 days so provider retries stay idempotent.
- Attachment bytes stay in existing uploaded-media / object-storage paths. They do not enter this table.

The table is fail-closed (`TeamScopedRootMixin`).
Cross-team sweepers must use `objects.unscoped()`.
Terminal states require `terminal_at`; non-terminal states require it to be null.
Queue transitions that use `QuerySet.update()` must set `updated_at` and the appropriate terminal timestamp explicitly.

Partial indexes cover pending due work, expired processing leases, payload cleanup, and terminal-row deletion.

Slack Events API and interactivity endpoints persist a receipt, then acknowledge Slack.
`X-Slack-Retry-Num` is stored as metadata. It is never used to drop a callback.
A Slack retry of a row that is waiting on backoff does not skip `due_at`.
Owning-region proxy failure returns 502 so Slack retries.
Celery `on_commit` dispatch is a wake-up hint with `apply_async(..., retry=False)`, so a hung broker cannot stall the Slack ack.
`sweep_inbound_events` (every minute) re-drives due and expired-lease rows, then drains payload cleanup and tombstone deletion in batches of 100 until a short batch or 20 rounds.

Workers claim a row with a fencing token and a 20-minute lease.
The lease covers a crashed worker. It is not a live handler wall-clock.
Receipt tasks have no Celery `time_limit`, because Slack ticket create plus thread backfill can run longer than a couple of minutes.
Completes, fails, retries, and lease renewals require `status=processing` and the claim's fencing token, so a retry that released the row cannot be settled by a stale worker.
Retry uses jittered backoff capped at 15 minutes, until 20 attempts or 24 hours.
Redis is not the dedupe record on the receipt path: losing Redis must not drop or suppress a callback.

Receipt workers use task names separate from the legacy payload tasks (`process_supporthog_event_receipt`, `process_supporthog_interactivity_receipt`).
Keep the legacy task names registered until payload tasks from the old endpoint have drained.
Live queue gauges (backlog, oldest ready age, last-sweep timestamp) are pushed through `pushed_metrics_registry`.
Do not emit a ClickHouse event for each sweep.

Slack thread backfill paginates `conversations.replies`, up to 25 pages (5,000 replies).
Workers call `renew_inbound_lease` between pages, once more before comment writes, and every 25 replies during comment construction.
A failed renewal (fencing miss or database error) is logged. The worker finishes the backfill anyway: the replacement worker skips backfill once the ticket exists, so aborting would drop the rest of the thread.
Fencing still stops the stale worker settling the receipt.

## Slack outbound bodies (`ConversationDelivery` / `ConversationDeliveryPart`)

One delivery per `(team, channel, comment_id)`.
The body is a part with stable `part_key=body`.
`team` is the canonical root team.
The part's `team_id` must match the delivery; the composite FK rejects a mismatch.

Enqueue the delivery and body part in the same transaction as the comment.
`Comment` is project-scoped; `Ticket` is environment-scoped. Match them on the canonical root team.
Snapshot destination and body at enqueue so a later comment edit cannot change what we post.
An oversized snapshot fails the part without payload and must not roll back the comment.
Generate one `client_msg_id` per body and keep it across retries.
Celery `on_commit` dispatch is a wake-up hint with `apply_async(..., retry=False)`.
`sweep_delivery_parts` (every minute) re-drives due and expired-lease parts, then drains snapshot cleanup.
Cleanup nulls payload and route on accepted or delivered parts only.
Failed parts keep their snapshots so manual redrive can still post.

Workers claim the part, not the parent delivery, with a fencing token and a 5-minute lease.
The claim transaction releases before `chat.postMessage` or the Slack file-upload HTTP calls.
Accept and fail update the part in one transaction.
Body accept also rolls the parent up and, in that same transaction, enqueues one pending part per image.
A 2xx (or a Slack error that still returns the original `ts`) marks the body `accepted`.
That is provider acceptance, not customer delivery.
Timeouts after a possible accept retry with the same `client_msg_id`.
Honor `Retry-After` on 429s, cap at one hour, and treat 5xx plus Slack timeout codes as transient.
Permanent Slack application errors (revoked token, missing channel, invalid blocks) fail the part.
Keep `post_reply_to_slack` registered for in-flight Celery messages.
New work uses `process_slack_delivery_part`.

Each image is its own part, keyed `image:<uploaded-media-uuid>` (or a hash of the URL when the path is not a UUID).
The payload stores resumable `get_upload` / `byte_upload` / `complete_upload` substates, plus Slack `file_id` / `upload_url` after get-upload succeeds.
Attachment bytes stay in object storage; the part never holds them.
A crash between Slack calls resumes at the persisted step and does not post the body again.
An expired upload URL resets the part to `get_upload` and retries.
Image and fallback failures do not change the parent's `accepted_at` or `provider_message_id`.
When every image part is terminal and at least one failed, enqueue a single `fallback` part with its own `client_msg_id` and the failed image URLs.
A second permanent image failure must not create a second fallback.
Posting the fallback waits if any image part is open again, then includes only currently failed URLs, so a redriven image that later succeeds is not linked.
The URL set is read under a lock on the image parts and written to the fallback part before the post, so a concurrent redrive either forces another wait or lands after the posted set is recorded.
A wait refunds the attempt the claim charged, and the last image to settle re-arms the waiting fallback, so a long redrive cannot exhaust the fallback's retry budget.
Manual redrive is allowed only for `failed` parts, and only after route and Slack workspace config still match the delivery's canonical team.
Redrive keeps `client_msg_id` (and image upload substate) and stamps `redriven_at`, which restarts the max-age window so an operator can still recover a failure older than 24 hours.
Redriving an image does not clear the parent's body acceptance.

## Outbound email (already in Postgres)

`EmailOutboxMessage` remains the outbound email outbox.
Do not rename or replace it.
Uncertain Mailgun sends and delivery-event correlation are additive columns on that table, not a new store.

## What must not happen

- Acknowledging Slack before the owning-region Postgres commit.
- Treating a Redis SET as the dedupe record.
- Retrying an already-accepted Slack body because an image upload failed (that is a delivery-part problem, not an ingress-row problem).
- Emitting raw Slack JSON or email bodies to ClickHouse.
