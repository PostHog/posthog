# Workflow email assets

**Status:** v1 implemented — PR [#65974](https://github.com/PostHog/posthog/pull/65974) on branch `posthog-code/workflow-email-assets`.
v2 (Warpstream-as-body-store) and v3 (crypto-shred for right-to-be-forgotten) sketched below as follow-ups.

**DRI:** @meikelmosby
**Last updated:** 2026-06-26 (Draft — accept a 6–12 month shelf life; rewrite into a permanent reference or delete after v3 ships)

---

## TL;DR

Workflow operators can see send metrics but can't open the actual emails their customers received.
We capture an immutable HTML snapshot per successful send, store metadata in ClickHouse (30-day TTL),
and surface a browsable Assets tab on the workflow scene.
v1 ships HTML snapshots to S3.
v2 swaps the body store to a Warpstream Kafka topic — cheaper at scale, atomic, one less subsystem to operate.
v3 adds crypto-shredding so right-to-be-forgotten is a single key drop.

---

## Problem

A workflow operator running an email campaign can't open the actual message a given customer received.

The send path renders Liquid → final HTML → hands it to SES → drops the in-memory body.
We persist counters (`email_sent`, `email_delivered`, `email_opened`, `email_clicked`) and Kafka log entries,
but **no copy of the rendered HTML exists anywhere after the SES call returns**.
The Metrics tab can tell you "47,302 sent / 318 bounced," and the Logs tab can tell you _that_ a specific person was emailed,
but neither can show you _what they saw_.

Concrete jobs this blocks:

- **Support / debugging** — "Customer X says the unsubscribe link is broken / the merge tag rendered as `{{first_name}}` / the image didn't load." Operator currently has no way to verify what was actually delivered.
- **QA on a live workflow** — after a batch ships, the only "did this render correctly?" loop is "wait for replies."
- **Audit / compliance** — "show me the exact message we sent this person on 2026-04-12." Required for some regulated industries; impossible today.

Send-time metric counters aren't a substitute — they count events, they don't archive content.

---

## Constraints that shape the solution

1. **Capture cannot fail the send.** By the time we have the rendered HTML, the SES call has already succeeded. Capture is strictly best-effort.
2. **Heavy-write / light-read workload.** A single batch can fan out to ≥100k recipients; hundreds of customers can run concurrent million-recipient batches. Reads are rare — operators occasionally spot-check, support occasionally drills in. Storage design should optimize for cheap writes; reads can tolerate noticeable latency.
3. **Rendering PDF at send time is prohibitive.** Headless Chromium per recipient at batch scale would dwarf the SES cost. v1 originally shipped on-demand PDF render; removed in commit `60056c7b694` — viewing the sandboxed HTML covers the support / QA jobs.
4. **The captured artifact is PII.** "Here is exactly what we sent to alice@example.com on this date" is more sensitive than "this workflow exists" — access must be gated above plain workflow read.
5. **Retention is bounded by policy, not feature.** 30 days covers support and QA; an indefinite archive is a compliance and cost liability.

---

## v1: what shipped

Capture one **immutable HTML snapshot per successful send** into object storage, plus one **compact metadata row in ClickHouse** to make it findable.
Surface the result in a new **Assets** tab on the workflow scene.
View-only (sandboxed iframe) — no download.

### Capture (Node — `MessageAssetsService`)

Injected into `EmailService`, called from the **success path only** after metrics are emitted.

- Writes the rendered HTML to object storage at a deterministic key: `message_assets/team-{id}/{functionId}/{invocationId}/{actionId}.html`.
- Produces one metadata row to the `clickhouse_message_assets` Kafka topic, partitioned by `invocation_id`.
- Wrapped in try/catch at every external-boundary call. Storage failures and Kafka-produce failures increment distinct prometheus counter labels (`stage='storage'` vs `stage='kafka'`). Neither failure ever throws.
- Gated by `MESSAGE_ASSETS_CAPTURE_ENABLED`.
- Skips standalone `hog_function` email sends (no `actionId` → unreachable via the workflow Assets API → no point writing).
- Skips text-only sends.

### Metadata store (ClickHouse — `message_assets`)

Modelled directly on `hog_invocation_results`.

- AUX cluster, single shard, replicated.
  One Kafka engine table + materialized view + local data table + distributed read alias.
- `ReplicatedReplacingMergeTree` keyed on `(team_id, function_kind, function_id, invocation_id, action_id)`,
  tie-broken by a microsecond-precision `version`.
- Partitioned by day of `sent_at`; bloom-filter skip indexes on `parent_run_id`, `distinct_id`, `person_id`, `recipient`.
- **30-day TTL** with `ttl_only_drop_parts = 1`.
- Holds only metadata. The HTML body never goes through ClickHouse or Kafka in v1.

### Retrieval API (DRF — actions on `HogFlowViewSet`)

Two actions, both scoped by team + workflow, both requiring `person:read` on top of workflow read.

- `GET .../hog_flows/:id/assets` — listing.
  Filterable by batch run (`parent_run_id`), email step (`action_id`), recipient (`distinct_id`),
  free-text `search` on recipient/subject, `after`/`before` (default `-30d`).
  Collapses to the latest non-deleted version per `(invocation_id, action_id)` via `argMax`.
- `GET .../hog_flows/:id/assets/content?invocation_id=…&action_id=…` —
  resolves the asset, **302s to a short-lived presigned GET URL** for the HTML.
  Django never proxies the body.

### Frontend (kea + React — Assets tab)

- **Batch-triggered workflows** group sends by `parent_run_id` using `LemonCollapse`, one panel per batch run.
- **Event-triggered workflows** show a flat searchable table.
- Clicking a row opens a `LemonModal` with an `<iframe sandbox="">` of the email (no `allow-scripts`).
- Each email step's "X sent" metric in the existing Metrics tab deep-links into the asset list filtered to that `action_id`.

### Architecture (v1)

```text
                          SEND PATH                                                RETRIEVAL PATH
─────────────────────────────────────────────────────────              ────────────────────────────────────
                                                                                       ┌──────────────────┐
   ┌────────────────────────┐                                                          │ React Assets tab │
   │ EmailService           │                                                          │ (WorkflowScene)  │
   │  .executeSendEmail()   │                                                          │  ├ list / search │
   └───────────┬────────────┘                                                          │  └ <iframe>      │
               │ success path                                                          └────────┬─────────┘
               ▼                                                                                │ GET /assets
   ┌────────────────────────┐                                                                   │ GET /assets/content
   │ MessageAssetsService   │  ← MESSAGE_ASSETS_CAPTURE_ENABLED                                 ▼
   │  .captureSentEmail()   │  ← skip: text-only OR no actionId                       ┌──────────────────────┐
   └─────┬──────────────┬───┘                                                         │ HogFlowViewSet (DRF) │
         │              │                                                             │  scope: person:read  │
         │              │  fails → counter{stage='storage'} (never throws)            └──────┬───────────┬───┘
         │              ▼                                                                    │           │
         │     ┌──────────────────┐                                                          │           │
         │     │ Object storage   │ ◄── presigned GET (60s) ─── 302 ──────────────────────────┘          │
         │     │  S3 / SeaweedFS  │                                                                      │
         │     │ message_assets/  │                                                                      │
         │     │  team-…/…/.html  │                                                                      │
         │     └──────────────────┘                                                                      │
         │     (31d S3 lifecycle)                                                                        │
         ▼                                                                                               │
   ┌──────────────────────────┐                                                                          │
   │ Kafka topic:             │ fails → counter{stage='kafka'}                                           │
   │  clickhouse_message_     │         → object orphaned until lifecycle purge                          │
   │  assets                  │                                                                          │
   │ partitioned by           │                                                                          │
   │  invocation_id           │                                                                          │
   └──────────┬───────────────┘                                                                          │
              ▼                                                                                          │
   ┌──────────────────────────┐                                                                          │
   │ ClickHouse (AUX cluster) │ ◄────────────── SELECT  (collapse via argMax(…, version),  ──────────────┘
   │  ReplicatedReplacingMT   │                          filter latest_is_deleted = 0)
   │  PARTITION BY toYYYYMMDD │
   │  TTL 30 days             │
   └──────────────────────────┘
```

### Failure modes (v1)

| Failure                         | Detection                                             | Blast radius              | Recovery                        |
| ------------------------------- | ----------------------------------------------------- | ------------------------- | ------------------------------- |
| Object storage write fails      | `cdp_message_assets_failed{stage='storage'}` + Sentry | One email's asset missing | Operator can resend if critical |
| S3 OK but Kafka produce fails   | `cdp_message_assets_failed{stage='kafka'}` + Sentry   | Orphaned HTML in S3       | Auto-purged at 31-day lifecycle |
| Standalone `hog_function` email | Skipped before write                                  | No asset captured         | Documented gap                  |

### Out of scope for v1

- **Reconciliation of S3 ↔ ClickHouse.** Orphaned objects accepted; the 31-day S3 lifecycle is the floor.
- **Standalone `hog_function` email destinations.** Skipped entirely until there's a UI to surface them.
- **PDF download.** Originally shipped; removed in commit `60056c7b694` — view-only.
- **Per-team retention override.** 30 days for everyone.
- **Search inside email body.** List search is recipient + subject only.
- **Right-to-be-forgotten via S3.** Today: enumerate via ClickHouse + delete each S3 object. Slow and brittle. Addressed in v3.

### TTL invariant (applies to v1 and v2)

> The body-store retention MUST be ≥ ClickHouse `message_assets` TTL + 1 day.

`ttl_only_drop_parts = 1` on a daily partition bounds ClickHouse's drop lag at ~24h.
A 1-day buffer on the body-store side guarantees:
**any row visible in the Assets list has a fetchable body**
(the reverse — body present, row dropped — is fine, nothing references it).

For v1 this means setting the S3 lifecycle rule to 31 days (not 30) while the CH TTL stays at 30.

---

## Planned v2: Warpstream-as-body-store

### Why

v1's per-email S3 PUT is fine at small scale but costs $0.005/1k requests,
which at hundreds-of-customers × million-recipient batches becomes a real line item ($50–$5,000/month in PUT cost alone).
More importantly, the workload pattern — **heavy writes, rare reads** — is exactly Warpstream's sweet spot:
the broker layer batches small produces into S3 segments for free,
so we get write-batching economics without rolling our own chunk format.
The direct HTTP fetch API ([docs](https://docs.warpstream.com/warpstream/kafka/reference/protocol-and-feature-support/http-endpoints))
makes random single-record reads a first-class supported pattern,
and bench testing in `WarpstreamFetchTester` showed acceptable latency for user-facing reads.

### Design

**Single topic, fire-and-forget produce, ClickHouse captures the Kafka offset via virtual columns.**

The metadata row and the HTML body live in the same Kafka message, on the same topic.
ClickHouse's Kafka engine already exposes `_partition` and `_offset` as virtual columns
(we use them today via `KAFKA_COLUMNS_WITH_PARTITION` in `posthog/models/message_assets/sql.py`),
so the MV materializes them into the data table — no producer-side offset capture required.
`html` is in the message value but the engine table schema doesn't list it,
so JSONEachRow parsing silently drops it at the CH consumer.

```text
Producer (single, fire-and-forget):
  produce(message_assets_topic,
          value = JSON.stringify({ ...metadata, html }))
  Done. No await on offset, no sequential second produce.

ClickHouse Kafka engine table:
  Schema lists only the metadata columns.
  JSONEachRow ignores unknown fields → `html` is dropped at parse time.

ClickHouse MV → message_assets_data:
  Copies metadata fields + virtual columns into the data table,
  renaming _partition → body_partition, _offset → body_offset for clarity.

Read (Django assets/content):
  1. CH SELECT → row contains body_partition + body_offset
  2. HTTP GET ${WARPSTREAM_HTTP_URL}/v1/kafka/topics/{topic}/
              partitions/{p}/records/{o}
     with Authorization: Basic <sasl creds>
  3. Parse JSON envelope, base64-decode `value` → JSON string
  4. JSON.parse → extract `html` field
  5. Return as text/html
  6. Map Warpstream 404 OFFSET_OUT_OF_RANGE to existing
     "Asset content is no longer available." 404.
```

**Warpstream HTTP API response shape** (already validated in `WarpstreamFetchTester`):

```json
{
  "offset": 42,
  "timestamp": 1707744000000,
  "key": "dGVzdC1rZXk=",
  "value": "dGVzdC12YWx1ZQ==",
  "headers": []
}
```

### Architecture (v2)

```text
   Send path                                            Retrieval path
   ─────────                                            ──────────────
   EmailService.executeSendEmail (success)              React Assets tab
            │                                                  │ GET /assets
            ▼                                                  │ GET /assets/content
   MessageAssetsService.captureSentEmail                       ▼
            │                                          HogFlowViewSet (DRF)
            │ produce(message_assets,                          │ scope: person:read
            │   value = JSON({ ...metadata, html }))           │
            │ fire-and-forget                                  │ 1. CH lookup → (p, o)
            ▼                                                  │ 2. HTTP GET to Warpstream
   Kafka topic message_assets (Warpstream)                     │    /v1/kafka/topics/.../
            │  31d retention                                   │     partitions/{p}/records/{o}
            │  max.message.bytes = 5MB                         │ 3. base64-decode value
            │                                                  │ 4. JSON.parse → html
            ▼                                                  │ 5. return text/html
   ClickHouse Kafka engine (drops `html` at parse time)        │
            │                                                  │
            ▼                                                  │
   message_assets_mv → message_assets_data
   (captures _partition + _offset as body_partition + body_offset)
            │
            ▼
   message_assets (distributed read alias)        ◄───── SELECT (collapse, filter not deleted) ─────┐
                                                                                                    │
                                                                                                    └── from Django above
```

### Why this is better than v1

- **Atomic single produce.** One side effect, no orphan window possible.
  If the produce fails, nothing else happens; if it succeeds, both metadata and body are landed.
- **One subsystem instead of two.** No bucket provisioning, no IAM dance, no S3 lifecycle rule, no presigned-URL signing.
- **Cheaper at scale.** Warpstream batches small produces into S3 segments;
  we pay their batching cost (which they've optimized for) instead of per-email S3 PUTs.
- **Single TTL knob.** Warpstream topic retention IS the TTL.
  No drift between CH TTL and S3 lifecycle to coordinate.
- **No producer-side offset capture.** The Kafka virtual columns give us the read coordinates for free.

### Trade-off

Body data now flows through the ClickHouse Kafka consumer even though CH doesn't materialize it.
At 100M emails/month × 50KB = ~5TB/month of bytes the CH ingestion layer reads-then-discards.
CH's Kafka MV path is built for this throughput shape — it parses JSON, takes the columns it knows,
drops the rest, moves on. The cost is bandwidth on the CH ingestion nodes,
which is the dimension CH is provisioned for.

If this ever becomes a CH ingestion bottleneck (it won't at these volumes, but if),
the escape hatch is splitting to two topics — same primitives, just split.
Future problem.

### Migration v1 → v2

Pure substitution: stop writing to S3, start writing to the new Kafka topic.
Assets captured before the cutover keep working via the existing `s3_key` path until the S3 lifecycle reaps them.

1. Add `body_partition` (UInt32) + `body_offset` (UInt64) columns to `message_assets_data` (CH migration).
2. Provision the `message_assets` topic on Warpstream with **31-day retention** and **`max.message.bytes = 5MB`**.
3. Deploy code that produces to the new topic (CH MV populates `body_partition` + `body_offset` from virtual columns automatically).
4. Two-phase read path in Django: prefer `(body_partition, body_offset)` if non-zero, else fall back to `s3_key`.
5. After 31 days (no S3-backed rows can still exist in CH), drop the S3 reader, the `s3_key` column, the bucket lifecycle rule, the S3 client code in Node, and the `OBJECT_STORAGE_*` config for this product.

### Open items for v2

- **Raise Warpstream `max.message.bytes` on the body topic** — default 1 MB will reject typical image-heavy emails. Set ~5 MB on this topic specifically (not cluster-wide) so the cap stays local. Mirror the change in the producer's Kafka client config.
- **Enforce a body-size cap at the editor / API boundary, not just at produce time** — the producer-side cap is a backstop, not a UX. The real fix lives upstream:
  - **Workflow editor** — when authoring or updating an email step, surface inline-image size in the editor, cap individual image bytes (e.g. 1 MB) and total rendered HTML (e.g. 4 MB after Liquid + tracking-pixel rewrite), and block save with a clear error if either is exceeded. Right now the editor lets you drop in arbitrarily large base64-inlined images and the constraint only shows up at send time.
  - **`HogFlow` save API (DRF)** — apply the same caps server-side on the email step's `html` / `inputs` so an MCP / API caller can't bypass the editor check.
  - Net effect: by the time anything reaches `MessageAssetsService.captureSentEmail`, the body is already known to fit. The Warpstream `max.message.bytes` then exists purely as a defense-in-depth ceiling, not a real constraint.
- **Bench the read path under realistic concurrency** — the existing `WarpstreamFetchTester` measured single-record fetch latency in isolation; the Assets API will issue these under user-driven load.

---

## Planned v3: crypto-shred for right-to-be-forgotten

### Why

Today (and after v2) right-to-be-forgotten requires enumerating every `invocation_id` ever sent to a person via ClickHouse,
then deleting from storage. Order-sensitive, fails if ClickHouse already TTL'd the row.
Crypto-shredding makes a single key-drop scrub every email asset for a person, regardless of where the bytes physically live.

### Pattern

Same as Session Replay's `dynamodb-keystore` (`nodejs/src/ingestion/pipelines/sessionreplay/shared/keystore/dynamodb-keystore.ts`):

- Per-`person_id` DEK generated via `KMS:GenerateDataKey`.
  AES-GCM encrypts the body with the plaintext DEK.
- The **encrypted** DEK lives in DynamoDB table `workflow_message_keys`,
  keyed by `(team_id, person_id)`, with `state: 'ciphertext' | 'deleted'`.
- On read: fetch encrypted DEK from DynamoDB → `KMS:Decrypt` → decrypt body.
  Cache plaintext DEK at request scope so listing N emails from the same recipient hits KMS once.
- On person-delete: `UpdateItem` atomically sets `state='deleted'` and `REMOVE encrypted_key`.
  Bytes stay; they're permanently unreadable.

### Why per-`person_id` and not per-message

Dropping one DynamoDB row scrubs every email asset for that person across every workflow and team they touched.
Per-message keying would mean enumerating + deleting per message — same problem we're trying to solve.

### Open questions for v3

- **Person merges.** A `personId` can change retroactively. Options:
  - re-encrypt under the new id on merge (expensive),
  - keep both keys live and try the survivor + merged-from ids on read (cheap; deletion-by-current-id can miss assets if there was an unobserved merge between capture and delete), or
  - write a small person-id-history lookup. Pick at v3 design time.
- **Empty `personId` at capture.** Some sends don't have a resolved person.
  Skip capture for those (matches v1's standalone-hog_function skip) —
  an undeletable asset is a worse failure mode than a missing asset.

---

## What still needs to happen for v1 to be live

1. Provision the `clickhouse_message_assets` Kafka topic in prod (already auto-created in dev).
2. S3 lifecycle rule on the `message_assets/` prefix, **31-day expiry** (applies the TTL invariant above — closes the existing edge between CH TTL and S3 lifecycle).
3. Run ClickHouse migration `0282_message_assets` (committed in `5260a95a503`).
4. Flip `MESSAGE_ASSETS_CAPTURE_ENABLED=true` in prod.
5. Run `hogli build:openapi` to drop the now-stale `hog_flows_asset_pdf_retrieve` from generated frontend types (PDF removed in `60056c7b694`).

---

## References

- v1 PR: [PostHog/posthog#65974](https://github.com/PostHog/posthog/pull/65974)
- Reference pattern for the ClickHouse table family: `posthog/models/hog_invocation_results/sql.py`
- Reference pattern for crypto-shred: `nodejs/src/ingestion/pipelines/sessionreplay/shared/keystore/dynamodb-keystore.ts`
- Warpstream HTTP endpoints: https://docs.warpstream.com/warpstream/kafka/reference/protocol-and-feature-support/http-endpoints
- Existing Warpstream fetch bench code: `nodejs/src/cdp/services/warpstream-fetch-tester.ts` (or wherever it lands when merged)
