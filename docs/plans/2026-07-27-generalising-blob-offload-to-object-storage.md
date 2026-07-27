# Should we generalise blob offload to object storage?

Status: investigation, no decision taken.

## The idea being tested

We write big payloads to S3 in several products and seem to rebuild the same thing each time.
Could we have one service that accepts arbitrary payloads, buffers them, writes efficient batches to S3, and returns a handle of the form `file:offset:length` for later point lookups?
Essentially the batching half of WarpStream without the Kafka protocol on top.

## Summary

The premise is half right, and the half that is wrong is the interesting half.

We have not built this three times.
We built it **once**, properly, in session replay, where it works well.
AI observability looked at the same problem and deliberately chose a different design, for good reasons.
CDP does not use object storage for this at all, also for good reasons.

The parts that are genuinely duplicated are shallow: S3 client setup, timeouts, retry classification, healthchecks, metric names, TTL conventions, handle encoding.
Worth extracting.
The parts that would justify a service are the parts that legitimately differ per product.

There is also a specific technical problem with the idea as stated: **`file:offset:length` is the wrong handle format for a service.**
It couples the handle to a physical placement decision, which is exactly the decision a batching service wants to defer.
Replay gets away with it only because its writer and its offset-committer are the same process.
Pull those apart and either the caller blocks on someone else's flush timer, or we hand out pointers to bytes that live only in one process's heap.

Recommendation: extract a shared library, not a service.
Revisit the service only if measurement shows PUT request cost or rate is actually hurting, and only for a caller that has no replayable input log.

## What we actually have today

### Session replay v2: this is already the proposed design

Replay implements the idea, end to end, today.

- `SessionBatchRecorder` buffers many sessions in memory in the Kafka consumer, keyed by `(teamId, sessionId)`.
- On flush it appends each session's compressed, encrypted buffer to a single multipart upload per retention tier, tracking byte offsets as it goes: `nodejs/src/ingestion/pipelines/sessionreplay/sessions/s3-session-batch-writer.ts:111`.
- The handle is literally file plus offset plus length, smuggled through one string: `s3://${bucket}/${key}?range=bytes=${startOffset}-${end}`.
- Reads parse it back and issue a real S3 range GET: `nodejs/src/session-replay/recording-api/recording-service.ts:79` and `:284`.
- Flush policy is size or age, default 100MB or 10s (`nodejs/src/ingestion/pipelines/sessionreplay/config.ts`).

So the question is not "should we build this?"
It is "should the thing replay built become a platform primitive?"

### AI observability: content-addressed, deliberately not batched

AIO offloads large base64 blobs out of AI event properties during ingestion, and chose the opposite design.

- One object per unique blob, keyed by content hash: `aio/{team_id}/sha256/{hash}` (`nodejs/src/ingestion/pipelines/ai/blob-offload/blob-store.ts:94`).
- The handle is a versioned, location-free pointer: `phaiblob://v1/sha256/<hex>?mime=...&size=...` (`nodejs/src/ingestion/pipelines/ai/blob-offload/pointer.ts`).
  That module's doc comment is worth reading, it is the best-designed piece of any of this.
- Dedup via HEAD before PUT.
  Lifecycle via self-COPY "touch" to reset object age against a bucket lifecycle rule.
- Reads proxy through Django for per-team authz, with immutable cache headers (`products/ai_observability/backend/api/ai_blob.py`).

### CDP: no object storage at all

CDP's size problem looked similar and got solved three other ways, none involving S3.

- Full invocation state lives in Postgres `bytea` on the Cyclotron job row (`rust/cyclotron-core/src/types.rs:46`).
- Large re-derivable fields are stripped rather than stored, then reloaded by the worker (`nodejs/src/cdp/services/job-queue/shared.ts:57`).
- The one field that dominated the Kafka lifecycle row gets gzipped inline (`nodejs/src/cdp/services/monitoring/hog-invocation-results.service.ts:246`).

No "TODO: offload to S3" markers anywhere in CDP.
This was a choice, not an omission.

### Others in the same neighbourhood

Error tracking symbol sets (presigned POST, 100MB cap, Postgres `storage_ptr`), exports (`content_location` with a DB fallback), tasks living artifacts (per-object `ttl_days` tag), and the general Temporal pass-by-reference rule in `AGENTS.md`.
Most of these are large single objects where batching is irrelevant, or they want presigned upload, or they want "give me a reference I can pass through a workflow".
Different problems wearing similar clothes.

## Why the divergences are essential, not accidental

**AIO's divergence.**
Dedup and packing are in direct tension.
You cannot dedup a needle inside an immutable pack without refcounting and rewriting.
The same image gets resent on every turn of a multi-turn LLM conversation, so content addressing collapses repeats that packing would store once per turn.
Content addressing also makes the read URL immutable and therefore browser-cacheable, which matters because AIO reads are random and human-triggered (an `<img src>` when someone opens a trace), not sequential like replay playback.
Batching would be a regression for AIO.

**CDP's divergence.**
Cyclotron state is transactional read-modify-write, not an immutable blob.
Packing mutable state into append-only objects generates a fresh needle per state transition, per retry, per fetch step.
And CDP's actual constraint was metered Kafka bytes, which gzip fixed for free with no new dependency and no new failure mode.
Routing that through a blob service would have added a network hop and an availability dependency to solve a problem that "don't store it" and "compress it" solved better.

So of three candidate customers, one already has it, and two would be worse off.

## What is actually duplicated

| Concern | Replay | AIO | Shared? |
| --- | --- | --- | --- |
| S3 client construction, endpoint and credential config | own builder | own builder | yes, trivially |
| Timeouts, retriable vs poison error classification | own | own (`BlobStoreError.isRetriable`) | yes, real duplication |
| Startup healthcheck before serving traffic | `checkHealth()` | PUT/HEAD/COPY sentinel | yes, real duplication |
| Prometheus metric shape (op duration, bytes, errors) | own | own | yes, real duplication |
| Versioned handle encode and parse | ad-hoc `s3://...?range=` string | proper `phaiblob://v1/...` module | yes, and AIO's is better |
| TTL and lifecycle coupling to row retention | tier prefixes | touch plus 31d lifecycle | same problem, different answers |
| Per-tenant read authz | recording-api plus Django | Django viewset scope | yes |
| Range-GET read client | yes | n/a | partial |
| Compression | snappy per session | none | no |
| Per-item encryption and crypto-shred | KMS plus DynamoDB | none | no |
| Batch buffering with durability-before-ack | yes | n/a | no |

The duplication is real but shallow.
It is the boring 200-line envelope around S3.
It is not the interesting part, because the interesting parts genuinely differ.

Three separate TTL mechanisms is the sharpest finding here.
AIO's has a fragile documented invariant, that the 31-day bucket lifecycle must outlive touch age plus the 30-day `ai_events` row TTL, enforced only by a `MAX_TOUCH_AFTER_HOURS = 24` constant and a comment (`blob-store.ts:252`).
An app-managed row TTL coupled to an infra-managed lifecycle rule, with the coupling living in a comment, is exactly the thing that should be one shared, asserted, tested convention.

## Three problems with the service as stated

### 1. The buffer needs a durability story, and today it gets one for free

This is the load-bearing objection.

Replay's buffer sits **inside** the Kafka consumer that owns the offsets.
It buffers up to 100MB or 10s and does not commit offsets until the multipart upload completes.
If the process dies mid-buffer, Kafka replays.
The Kafka log is the write-ahead log for the buffer, at zero extra cost.

AIO gets the same property differently: the upload happens before the rewritten event is emitted, so the input partition is again the WAL ("Upload-before-emit: every blob must be confirmed durable before the rewritten event exists anywhere", `offload-ai-blobs-step.ts:157`).

Extract that buffer into a service and the caller does `POST /blobs` and needs a handle back.
Two options:

- **Ack after flush.**
  Honest, but the caller's p99 is now the flush interval.
  Replay's is 10s.
  An in-process memory append becomes a synchronous cross-network call gated on another service's batch timer, and we have serialised two independent batching loops and inherited that service's availability.
- **Ack before flush.**
  Fast, but we have handed out a pointer to bytes that exist in one process's heap.
  If it dies, dangling pointers are already written into ClickHouse.
  To fix that the service needs its own WAL, which is Kafka or small S3 objects, that is, the complexity we were trying to avoid.

The way out is that **the handle must not depend on placement.**
If it is a content hash, the caller computes it locally with no round trip, and the write becomes genuinely async and retryable.
Which is what AIO already does.
So `file:offset:length` is self-defeating for a service, and the fix requires an index mapping hash to (file, offset, length).
Both Haystack and the CMU packing work name that metadata tier as the real scaling bottleneck, not the data tier.

### 2. Deletion and retention are where packing bites, and they are per-product

You cannot punch holes in an S3 object.
Once multiple tenants' items share one object:

- **Per-item deletion by deletion is impossible.**
  Replay's answer is crypto-shredding: a per-session KMS data key in DynamoDB, deleted on request, after which the bytes are unreadable (`recording-service.ts:344`).
  Good answer, but a generalised service either owns per-item keys and a keystore for every customer whether they want it or not, or exposes a shredding hook and each product brings its own.
- **Mixed retention in one object is impossible.**
  Replay shards batch files by retention tier, so four tiers means four concurrent multipart uploads per batch (`retention-aware-batch-writer.ts`).
  A service must be told the retention class at write time and shard buffers accordingly.

There is a security property here worth stealing regardless of what we build.
Because each replay session is encrypted under its own key, an offset arithmetic bug yields undecryptable garbage rather than another customer's bytes.
Per-item encryption makes packing bugs **fail closed**.
Any generalised packer should require it.

### 3. Buffer fragmentation is the real scaling limit

Batching only pays if buffers fill.
Required buffers multiply as product times retention tier times region times anything else that cannot be mixed.
Add per-team isolation, which we might want for deletion or data residency, and the long tail of small teams flushes on the timer rather than the size threshold, producing exactly the small objects we were trying to avoid, now with an extra service in the path.

Replay dodges this by not sharding by team, mixing teams in one object and paying for it with crypto-shredding.
That is the trade a generalised service must also make.

## Is the cost win even real?

Worth doing this arithmetic before designing anything, because it decides the whole question.

Public S3 Standard rates: PUT $0.005 per 1,000, GET $0.0004 per 1,000.
So:

- Writes cost 12.5x reads.
  The prize is entirely on the write side.
- 1B PUTs per month is $5,000.
  Batched 1,000:1 it is $5.
- **Range GETs cost the same as full GETs.**
  Batching does not reduce read request cost at all, and can increase it if a logical read needs an index lookup plus a data fetch.
- S3 Standard has **no** minimum billable object size.
  The widely-cited 128KB minimum applies to Standard-IA, Glacier Instant Retrieval, and Intelligent-Tiering.
  Our blobs have roughly 30-day TTLs and never tier, so that argument does not apply to us.
  The storage-class case for packing is close to worthless here.

That leaves exactly one prize: **fewer PUTs.**
Which gives a clean qualifying test.
Does this product write a very large number of individually small objects?

- Replay: yes.
  Batching is correct there.
- AIO: less so.
  The offload floor is around 15KB decoded, the per-event cap is 50 blobs, and dedup collapses repeats.
  Note that dedup is *already* a request-cost optimisation, since a HEAD that hits an existing object is charged at GET rate rather than PUT rate.

Two things follow.

**Compaction is the wrong tool.**
Writing small objects and packing them in the background is the classic data lake answer, and it is attractive because it keeps the hot path simple.
But it delivers storage economics, tiering eligibility, and read locality, which are the three wins we just established are nearly worthless here.
It does not reduce PUT count, it increases it.
Only write-side batching reduces PUT count, and write-side batching is precisely where the durability problem in problem 1 bites.
That is not a coincidence, it is why replay put its buffer in-process.

**The cheapest experiment is a config change, not a service.**
Since the April 2025 repricing, S3 Express One Zone is roughly 4.4x cheaper per PUT and 13x cheaper per GET than Standard, at roughly 4.8x storage cost plus per-GB upload and retrieval fees.
For short-lived, high-write-count, small-object data, which is exactly this workload shape, that captures a real slice of the win with zero new code.
The per-GB fees are the trap and can exceed the request savings, so it needs modelling against actual object sizes and TTLs, but it should be modelled first.

## If we did build the service, this is its coherent form

Not a synchronous `POST` that returns `file:offset:length`.
That shape cannot be made both fast and durable.

Instead:

1. Producer hashes the payload locally and writes the content-addressed pointer into its row immediately.
   No round trip, no blocking.
2. Producer publishes the bytes to a blob topic.
   Kafka is the WAL.
3. A packer consumer buffers, shards by retention class, packs, uploads, and writes `hash -> (file, offset, length)` into an index.
4. Reads resolve through the index, then issue a range GET, decrypt, decompress.

This works, and it is close to what replay already is, just generalised with an index in front.
The costs are explicit: a new index tier to operate and shard, and pointers become **eventually** resolvable rather than durable-before-emit.
That last point is a real regression against AIO's current guarantee, and would need a resolver that can distinguish "not packed yet" from "lost", which means the pointer needs its own durability tracking.
That is most of a database.

## Recommendation

**Stage 0, now, cheap: measure.**
For each candidate get PUT count per day, bytes per day, mean object size, read QPS, read latency budget, mutability, TTL, and dedup ratio.
The decision is essentially determined by PUT count per byte.
Without those numbers this is unfalsifiable, and the S3 Express One Zone comparison cannot be run either.

**Stage 1, now, worth doing regardless: extract a library, not a service.**
This is the part that is genuinely duplicated, and it is a refactor with low risk.

- One versioned handle codec.
  Generalise AIO's `phaiblob://v1/...` design, which is already right in that it is location-free and resolver-owned, so that it can also express packed locations behind the same opaque string.
  That is what lets a product change write strategy later without rewriting rows, and it is the highest leverage thing here.
- One S3 envelope: client construction, timeouts, retriable vs poison classification, startup healthcheck, standard metric names.
- One TTL and lifecycle convention, with the row-TTL versus bucket-lifecycle invariant asserted in code and covered by a test, replacing the three ad-hoc mechanisms we have now.
- One read-path helper: parse handle, authorize team, range GET, decrypt hook, decompress hook, immutable cache headers.
  The read side generalises far better than the write side, and it is off the ingest hot path.

**Stage 2, only if Stage 0 justifies it: add packing as a library backend for one product.**
In-process, sharing the caller's Kafka WAL, as replay does.
Requirements: content-addressed handles so they are placement-independent, per-item encryption so offset bugs fail closed, retention-class buffer sharding, and a GC story.

**Stage 3, probably never: the standalone service.**
It is only justified for a caller that has no replayable input log, writes many small objects, and can tolerate either flush-interval latency or eventually-resolvable pointers.
No current PostHog caller clearly meets all three.
If one appears, build the form described above rather than a synchronous offset-returning API.

## Open questions

- Do the numbers in Stage 0 put anything other than replay over the line?
- Does S3 Express One Zone beat building anything, for the short-TTL cases?
- Is replay's decision to mix teams within one object something we want to standardise on, given it makes per-item encryption mandatory rather than optional?
- Should the handle codec live in the Node monorepo, in Python, or both, given AIO writes in Node and reads in Django, while replay writes in Node and reads via a Node service that Django proxies?

## References

- [Finding a Needle in Haystack: Facebook's Photo Storage (OSDI '10)](https://engineering.fb.com/2009/04/30/core-infra/needle-in-a-haystack-efficient-storage-of-billions-of-photos/)
- [A Case for Packing and Indexing in Cloud File Systems (CMU/Alluxio, HotCloud '18)](https://www.pdl.cmu.edu/ftp/CloudComputing/HotCloud18-kadekodi.pdf)
- [AWS: Optimizing storage costs by compacting small objects](https://aws.amazon.com/blogs/storage/optimizing-storage-costs-and-query-performance-by-compacting-small-objects/)
- [AWS: Up to 85% price reductions for S3 Express One Zone](https://aws.amazon.com/blogs/aws/up-to-85-price-reductions-for-amazon-s3-express-one-zone/)
- [S3 pricing](https://aws.amazon.com/s3/pricing/)
