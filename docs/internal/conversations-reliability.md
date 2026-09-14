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

## Outbound email (already in Postgres)

`EmailOutboxMessage` remains the outbound email outbox.
Do not rename or replace it.
Uncertain Mailgun sends and delivery-event correlation are additive columns on that table, not a new store.

## What must not happen

- Acknowledging Slack before the owning-region Postgres commit.
- Treating a Redis SET as the dedupe record.
- Retrying an already-accepted Slack body because an image upload failed (that is a delivery-part problem, not an ingress-row problem).
- Emitting raw Slack JSON or email bodies to ClickHouse.
