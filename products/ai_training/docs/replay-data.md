# ML replay data

The Django controls and their tests live in `products/ai_training/backend/`, owned by AI Research.
Application lifecycle hooks use the product facade; the models share the main database to preserve atomic transactions.

AI Research owns the ML mirror, its encryption keys, and its training readers.
The mirror collects scrubbed recordings from organizations that consent to AI training.
Its storage and deletion implementation is separate from production session replay.

## Session versions

The cutoff is **Tuesday, 2026-09-15 at 12:00 UTC**, which is 13:00 in Europe/London.
The session UUIDv7 timestamp selects the version:

- Before the cutoff: v1 uses HMAC team and session IDs.
- At or after the cutoff: v2 uses raw team and session IDs and encrypted payloads.
- At or after **Monday, 2026-09-21 at 17:00 UTC** (18:00 in Europe/London): v3 keeps the v2 identifiers and keys, and stores its objects in the v3 buckets under `rrweb_3/` and the `/v3/` dataset paths. Its metadata catalog and evaluation index are plain Parquet.
- The ML mirror drops a session if its ID is not UUIDv7 or its start year is beyond 9999.

Event timestamps, arrival times, retries, and flushes do not change the version.
Both versions can occur in one ingestion batch.
Their replay blocks, images, and metadata use separate storage paths.
The version applies to the whole session, including a session that crosses the cutoff.
An image reference carries the dataset version of the session that collected it, so a v3 session's images are v3 whatever their month, and the image lanes never read a session ID.
The three lanes require `AI_RESEARCH_REPLAY_S3_BUCKET` at startup, because a v3 session or image has no other place to go.

## Consent

Ingestion uses the organization's existing `is_ai_training_opted_in` flag for both versions.
The team lookup caches this flag for up to five minutes.
Withdrawing consent stops collection after that refresh and preserves previously collected data and keys.
Re-enabling consent resumes existing sessions as well as new sessions, using their existing keys.
Messages already admitted to the mirror can finish processing.
Session start time selects the dataset version and monthly partition only.
There is no separate consent model, DynamoDB consent entry, consent timestamp, or initialization command.

## Keys and batch processing

The independent DynamoDB table stores session keys, team image keys, deletion markers, and monthly key indexes.
A team image key is wrapped by KMS.
A session key is sealed under the team image key of its month, so KMS holds one key per team per month, not one key per session.
A session key stored before this change carries its own KMS blob, and every reader opens both shapes.
HKDF-SHA256 makes the key that seals session keys from the stored team image key, which still seals image data itself.
The `recording_blob_ingestion_v2_ml_key_scheme_total` metric counts session keys by scheme and leaves team image keys out, so v2 reaches zero when no session key predates v3.
ML outputs omit distinct IDs, including their hashes and pseudonyms.
The metadata consumer projects supported fields before storage, including for messages already in Kafka.
A session has one data key.
A team has one image key per session start month.
KMS wraps each key it holds with an encryption context that binds the team, the session or month, and the purpose.
A sealed session key authenticates the same context.
A team can change organization while a session is open, so the organization is not part of that context; keys wrapped before this change carry the organization they were wrapped under on their row, and the mirror unwraps them under it.
The replay lane that serves playback encrypts a block with XSalsa20-Poly1305, which is a different format: nothing this lane writes uses it.
The authenticated payload also binds the dataset kind and, for images, the object or reference being encrypted.
The envelope seals the raw payload with AES-256-GCM.
Its additional authenticated data is the JSON of `{"v": 3, "context": ...}` with sorted keys and no whitespace.
An envelope takes one of two shapes, and where it is stored decides which.
An object body is a binary frame: the ASCII magic `AISR03`, the length of the additional authenticated data as a 16-bit big-endian integer, those bytes themselves, the 12-byte nonce, then the sealed bytes followed by the 16-byte tag.
The frame carries those bytes verbatim, so a reader passes them to AES-GCM as they are rather than rebuilding the canonical JSON and risking a re-serialization mismatch.
A reader must still decode that context and check it equals the object it asked for, because one team month key seals every image object in a flush and the context is the only thing that tells them apart: a reader that skips the check authenticates a shard where it expected an index, or one image's location where it expected another's.
A reader must also bound the frame before it slices, because the magic and the length sit outside the authenticated data.
In the v2 dataset, a parquet column holds a value and not an object body, so `metadata` and `replay-index` stay JSON with `v`, `context`, `nonce` (12 bytes, base64) and `ciphertext` (the sealed bytes followed by the 16-byte tag, base64). A reader there knows the shape from the column and inspects no magic bytes.
The v3 dataset does not seal its metadata or its replay index. Both are plain Parquet columns, described in [Data layout and readers](#data-layout-and-readers).
The `frame` block in `nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/keys/encryption-vector.json` pins one frame with a brotli body, so a reader in another language can check its own bytes. It carries the whole frame and also each part on its own: the additional authenticated data as text, the nonce, the sealed bytes, the tag, the brotli body, and the decompressed data.
The framed context names a `codec`, which tells a reader how to expand the plaintext.
An `rrweb` block uses `brotli` at quality 9. Each lane declares its own codec, so this lane never produces snappy. It reads a block rarely and keeps it for months, so it stores fewer bytes instead.
An image object uses `none`, because an image already arrives compressed.
A sealed session key row carries `sealed_key` and `key_nonce`, and carries no `wrapped_key`.
HKDF-SHA256 makes its 32-byte wrapping key from the stored team image key, with an empty salt and the info string `ml-session-key-wrap`.
AES-256-GCM then seals the session key under that wrapping key.
`key_nonce` holds the 12-byte nonce, and `sealed_key` holds the sealed bytes followed by the 16-byte tag.
Its additional authenticated data is the JSON of `{"purpose": "ai-research-session", "team_id": ..., "session_id": ...}` with sorted keys and no whitespace, so every reader rebuilds the same bytes.
The `seal` block in `nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/keys/encryption-vector.json` pins one seal, so a reader in another language can check its own bytes.

Ingestion processes key state in batches:

1. Bulk-read session keys and image keys in one pass. A session's start month names its image key, so the batch knows every row before it reads.
2. Resolve keys in memory while processing the batch.
3. Write each new key's month index entry, then the key with a conditional put.
4. Adopt the key a competing writer stored, which the refused put returns, then publish replay blocks or image messages.

A conditional put refuses to recreate a shredded session key.
A shredded team image key stops its team month for good, and this is the reason the table holds no team block row.
The shred sets the tombstone and removes the key material in one update.
A batch that meets a tombstoned image row does not add that month key to its keys, so it never writes the row again, and a conditional put would refuse it in any case because the row exists.
A session in that month then finds no month key, so the batch mints no session key and stores none, and it counts the session as `month_key_unavailable`.
Every reader drops the same sessions, because the seal only opens under a month key that no longer exists.
The deletion worker sweeps the team once, and that sweep removes rows to save cost. A key stored after the sweep passes a shard is sealed under a month key the deletion already tombstoned, so a second sweep finds nothing that is readable.
A team deletion also closes the previous month, the current one and the next one, because a sweep reaches only an image key that already exists. Ingestion admits a session up to `ML_SESSION_MAX_AGE_DAYS` old, so those three are every month a later session can still open.
Consent stops collection after that, not deletion: a team that keeps its opt-in and keeps sending opens a later month again.
Kafka offsets advance only after the required writes and publication succeed.
Bulk reads use batches of at most 100 keys. Each new key is one conditional put, so no commit in the fleet waits on another, and the month index entries it needs go in together, at most 25 to a request.
Batches overlap, so a session first seen in one batch and also present in the next costs a second conditional put, which loses and settles on the stored key.
Reads use strongly consistent `BatchGetItem` requests with bounded retries for unprocessed keys and for a throttled request.
A retry stops when the caller's deadline expires.

The mirror runs each Kafka batch through three stages that each hold one batch at a time, in batch order: prepare (steps 1 and 2, with session tracking), anonymize (the scrub), and commit (steps 3 and 4, then offset tracking and any flush).
Neighboring batches overlap across stages, so one batch waits on DynamoDB, KMS, Kafka or S3 while another scrubs.
The anonymize stage does not admit a batch while an earlier batch is in it.
The record step writes to the recorder that is current at commit time, not the one that was current when the batch was read from Kafka, so a flush between those two moments does not lose the batch.

Ingestion holds a usable session key row and image key row in the process, and a KMS plaintext cache reduces repeated decrypt calls.
A row with no wrapped key is never held, so a repaired row is seen at once.
A tombstone is held, because a shred only ever sets one and a conditional put cannot overwrite a row that exists, so a deleted session stops costing a read and a refused write on every batch.
A session key deleted out of band stays usable in a process that already read it, until that entry expires.
`ROW_CACHE_LIFETIME_MS` therefore sets how soon ingestion observes a session deletion.
A sealed session key keeps that same bound, because its seal lives on the session row and nothing else holds it.
The team image key stays cached far longer, but it opens no session on its own.
A team image key is held for an hour, because it is one row per team per month and a longer lifetime costs far fewer reads. A shred removes the durable key, so a process that runs on a held row of either kind writes data that no reader can open.
Data written under such a key stays unreadable, because the envelope stores no key, and the stored row is a tombstone with no wrapped key, no seal, and no nonce.
Training readers do not use this cache.
Each process limits KMS concurrency and request rate; deployment capacity must account for the sum across replicas.
Readers check live state before each batch and permit key use for at most five minutes from the start of that read.
An expired read must obtain permission again.

The key table has no TTL or point-in-time recovery.
Its resource policy denies backups, exports, and enabling continuous backups or Kinesis copies.
Do not copy wrapped keys into object storage, logs, workflow payloads, or another persistent cache.
A restored key defeats deletion, whether KMS wrapped it or a team image key sealed it.

## Deletion

Existing recording, person, team, and organization deletion flows enqueue ML deletion work.
Person deletion resolves the combined supplied and profile distinct IDs through the replay ClickHouse index.
This lookup also runs when the user does not select replay deletion and includes IDs with no remaining person profile.
Only the resulting session IDs enter the ML deletion outbox.
The lookup runs in a background task, so person deletion waits only until the task is queued.
The task carries the distinct IDs, because the profile they belong to is deleted by then.
A failed lookup retries with backoff for about 24 hours, then fails the task, which the task failure metric reports.
Team deletion and its deletion outbox request commit in the same database transaction.
If the outbox write fails, team deletion fails and can retry.
Consent changes do not enqueue deletion requests.
The outbox survives removal of the source team or organization.
Its team IDs refer to the original environment, without resolving a child environment to its parent.

| Scope   | Effect                                                                                    |
| ------- | ----------------------------------------------------------------------------------------- |
| Session | Remove its wrapped key, its seal, and its nonce, then permanently block that session ID.  |
| Person  | Resolve its session IDs through replay, then apply session deletion to each result.       |
| Team    | Remove its session keys and its image keys, and close the current month and the next one. |

The person lookup matches any available replay row for the requested IDs that began before the deletion, then deduplicates and paginates sessions.
It does not filter out recordings marked deleted or past their replay retention date while their index rows remain.
Replay index retention limits this lookup: after those rows expire, person deletion cannot discover the corresponding ML sessions.
New sessions from the same person can be collected if consent permits them.
Team lookups use 32 session shards with strongly consistent DynamoDB queries.
Deleting a resolved session removes all of its events, including events from other identities.

Deletion uses resumable query pages and stores progress in the outbox.
A failed request backs off without blocking unrelated requests.
Completion follows key removal and the five-minute reader lifetime.
Scrubbed images remain available after session or person deletion, but become unreadable after team or month deletion.

This mechanism covers encrypted v2 and v3 objects.
It does not erase legacy plaintext objects, plain v3 metadata and index rows, previously downloaded data, derived training artifacts, or a trained model.
Legacy dataset retirement needs a separate storage operation before claiming deletion across the entire bucket.

## Monthly key deletion

Key creation writes the month index entry with a plain put, then the wrapped key with a conditional put.
The index entry comes first, so every stored key has an index entry.
An index entry without a key is harmless: the month sweep leaves a tombstone that a later key put respects.
The index uses 32 partitions named `month:<YYYY-MM>:shard:<0..31>` and stores key locations, without copying wrapped keys.
Session keys and image keys appear in this index.

Run `python manage.py delete_ai_training_month YYYY-MM` to remove the keys of that UTC session month.
The mirror drops a session whose ID started more than 14 days in the past or more than 1 day in the future, and the command accepts a month from 14 days and one hour after the month ends, so a batch admitted just inside the limit cannot commit a key after its index shard was swept.
Neither side reads a shared block item for the month, because every commit in the fleet would contend on that one DynamoDB item.
The command uses strongly consistent queries and bounded writes.
Rerun the command after an interrupted run; it safely repeats completed pages.
Rerun it once for any month that an earlier version of the command deleted, because readers no longer honor the month block that version wrote.
A reader that already cached a key can still use it.
The matching monthly S3 folders can then be removed from each dataset.
Deleting a month does not affect another month's image keys.

## Data layout and readers

All v2 S3 datasets use a `YYYY-MM` directory derived from the session UUIDv7 start timestamp in UTC.
A session that crosses a month boundary stays in its start month, including late blocks and image fetches.

| Dataset              | Default path                                                | Encryption key                           |
| -------------------- | ----------------------------------------------------------- | ---------------------------------------- |
| Replay blocks        | `rrweb_2/<month>/`                                          | Session                                  |
| Metadata catalog     | `block-metadata/v2/<month>/`                                | Each row's payload uses its session key  |
| Evaluation index     | `block-metadata-replay-index/v2/<month>/kind=<kind>/`       | Each block and kind uses its session key |
| Inline image shards  | `scrubbed-images/v2/<month>/<team>/shards/`                 | Team and session month                   |
| Inline image lookups | `scrubbed-images/v2/<month>/<team>/lookup/<hash>.encrypted` | Team and session month                   |
| Inline image indexes | `scrubbed-images/v2/<month>/<team>/index/`                  | Team and session month                   |
| URL images           | `scrubbed-images/v2/<month>/<team>/url/<hash>`              | Team and session month                   |

A v3 session uses the same layout in the v3 buckets: blocks under `rrweb_3/<month>/`, and the metadata catalog, the evaluation index and every image path with `/v3/` in place of `/v2/`.
The v3 metadata catalog and the v3 evaluation index use no key.
Some v3 objects under those two paths are sealed, mostly under 2026-09. A sealed object has a `payload` column that holds an encrypted JSON envelope, as in v2.
A reader checks each object for a `payload` column in every month. See [the structured data index](../../../docs/internal/session-replay-structured-data-index.md#plain-v3-index-and-metadata).
A reader finds the bucket of a block in its `block_url`, and resolves an `image:v3:` or `imageurl:v3:` reference in the v3 images bucket under the `/v3/` paths.

A v2 metadata catalog exposes raw `team_id`, `session_id`, `format_version`, and an encrypted `payload`.
URLs, block locations, and replay indexes are inside that payload.
Neither the catalog nor its encrypted payload includes a distinct-ID field.
V2 does not write a separate plaintext replay index.

A v3 metadata catalog stores each block as plain Parquet columns: raw `team_id` and `session_id`, the block location, timestamps, counts, and the scrubbed `first_url` and `urls`.
It has no distinct-ID field and no replay index entries.
The v3 evaluation index stores its entries as plain Parquet columns with raw team and session IDs and the scrubbed URL.
Deletion does not remove v3 metadata or index rows. The sink reads no session key for a v3 row, so it also writes rows for a session that was deleted after the mirror produced them.
Those rows hold no personal data, and the recording blocks they point to become unreadable when the session key is shredded and the cached copies of that key expire.

Athena can select v2 catalog rows but cannot decrypt replay fields. It can query every column of a plain v3 object.
To leave out sealed v3 objects, include a `payload` column in the table and filter on `payload IS NULL`.
Training readers must bulk-read live keys and deletion markers before decrypting.
If a download exceeds the key read lifetime, readers must check live eligibility again before decryption.
Cross-account readers use the full DynamoDB table ARN and the prod-us KMS key ARN.
Both accounts must authorize the reader role.
Readers have key-read and decrypt permissions; they cannot create keys or change deletion state.

Use metadata block locations and byte ranges to fetch recordings, then decrypt before decompressing.
Read metadata from the session start month, including blocks that arrive in later months.

Join analytics on both raw team and session IDs.
Remove identifiers from model inputs.
Resolve image references before training because they contain team IDs.

## Images and Kafka

A reference names its dataset version: `image:v2:<team>:<month>:<hash>` and `imageurl:v2:<team>:<month>:<hash>` for a v2 session, `image:v3:...` and `imageurl:v3:...` for a v3 session. The version is part of the reference, so the fetch frontier and every dedup cache treat a v3 reference as new even when a v2 session already stored the same image, and the v3 dataset gets its own copy.
Images do not deduplicate across teams or session months.
Kafka records between the ML lanes travel in cleartext.
In S3, recording blocks and images are sealed, and stored scrubbed images use team image keys.
V2 metadata and the v2 evaluation index are sealed. V3 metadata and the v3 evaluation index are plain Parquet, apart from the sealed v3 objects that [Data layout and readers](#data-layout-and-readers) describes.
Consumers reject malformed UUIDv7 session identifiers before reading DynamoDB.
Oversized identifiers cannot fail a whole bulk key lookup.
Inline images have an encrypted lookup for each reference, published after the shard and its index.
Readers fetch that lookup directly; a missing image does not require a scan of the team's image history.
The image scrubber hands the images it scrubbed to a write lane every 30 seconds or when its buffer is full, writes them while it scrubs the next batches, and writes the shard groups of one hand-off concurrently.
The offsets of a hand-off are stored after its writes complete, in hand-off order, so a failed write stops every later store and the pod replays from the last stored offset.
Source deduplication uses the image reference, which names the team and the session month, so one fetch serves every session of that team month.
Session deletion does not remove images, so a session cannot lose an image that another session fetched.
The v2 image-fetch frontier uses a separate, initially empty DynamoDB history table.
Its URL history expires eight days after the end of the session's UTC month.
HTTP freshness and cache directives do not change this expiry, because the stored image for a team, month and URL is write-once.
A `no-store` response leaves no cache metadata in that history.
Robots.txt and TDM reservation caches keep their shared origin keys and existing expiry rules.
It does not inherit v1 seen flags or successful fetch results.

ML Kafka producers write `ai_research_ingestion_version: 1` or `2`.
Retries and dead-letter replay preserve this header and the record bytes.
Consumers drop records that still use the sealed envelope shape from before cleartext records, and count them in `recording_blob_ingestion_v2_ml_legacy_envelopes_dropped_total`.
Headerless queued messages mean v1.
Unknown versions are rejected, and so is an image reference whose version does not match the header.
For a v2 session, the metadata sink resolves each row's session key from the row's own team and session identifiers before it seals the row for Parquet; a row whose key is deleted is dropped.
A v3 row needs no key, because the sink writes it as plain Parquet.

Legacy image references and paths remain available for v1 sessions.
Their HMAC key must remain stable while that data is in use.

## Configuration

New key manager and v2 storage settings use the `AI_RESEARCH_REPLAY_*` prefix:

- `KEY_TABLE`, `KMS_KEY_ARN`, and `AWS_REGION` select the key store and wrapping key.
- `KEY_CACHE_MAX`, `KEY_CACHE_LIFETIME_MS`, and `KMS_REQUESTS_PER_SECOND` bound the KMS plaintext cache and KMS traffic.
- `ROW_CACHE_MAX` and `ROW_CACHE_LIFETIME_MS` bound the stored key row cache. The lifetime applies to a session key row and is capped; a team image key row is held for up to 48 hours. A value that is not a positive integer stops the consumer at startup and names the setting.
- `IMAGE_FETCH_V2_DYNAMODB_TABLE` selects the fresh v2 frontier.
- `S3_PREFIX` selects v2 replay storage and defaults to `rrweb_2`.
- `S3_BUCKET` names the v3 bucket of a lane. A session that started at or after the v3 cutoff writes there, and v2 keeps its own bucket. The mirror and the metadata sink use the recording bucket, which holds AISR03 frames for recording blocks and Parquet for the v3 metadata catalog and evaluation index. The image scrubber uses the images bucket, which holds AISR03 frames. The mirror, the sink and the image scrubber stop at startup when it is empty.
- `S3_V3_PREFIX` selects the block prefix inside the v3 bucket and defaults to `rrweb_3`. Each dataset version has its own prefix, so a bucket policy grants only the versions it holds.

The v2 producer requires `AI_RESEARCH_REPLAY_KEY_TABLE` and `AI_RESEARCH_REPLAY_KMS_KEY_ARN` at startup.
Missing values stop startup before it consumes Kafka messages.

Established HMAC settings retain their transition aliases.
When both aliases are set, the `AI_RESEARCH_REPLAY_*` value takes precedence, including an explicit empty value.
The wrapped HMAC secret keeps the single name `SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY` in both the environment and secret store.
It has no new alias.
Renaming configuration must not rotate that key.

The shared ML server configuration applies the legacy aliases before explicit server overrides.
An image scrubber with the key manager enabled must configure `SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC` before startup.
Malformed encrypted images retain their original payload and headers in the dead-letter queue.
The scrubber retries failed dead-letter writes and interrupts retry waits during shutdown.
The image fetch consumer dead-letters unsupported ingestion version headers while processing other valid records in the batch.
A v2 message without key manager configuration still fails the batch because it needs the missing encryption settings.

V2 data uses `YYYY-MM` directories from the session UUIDv7 start timestamp in UTC.
Recording blocks, metadata, image shards, image lookups and URL images retain that month across late arrivals.
V2 image references include `<team>:<month>:<hash>`, so the image-fetch seen history is independent for each month.
Robots.txt and TDM reservation caches remain shared by origin across months.

## JSON-LD evaluation index

The v2 metadata consumer writes a separate encrypted index for `json_ld`, `full_snapshot`, and `page` entries.
The path uses the session's UTC start month, even when events or uploads fall in a later month.
Each Parquet row exposes real `team_id` and `session_id` values and encrypts the projected entries with the session key.
Session, person, team, and month deletion therefore remove access to the index along with its recording.
The JSON-LD payload remains in the referenced recording block.

The v3 metadata consumer writes the same three kinds as plain Parquet columns with real team and session IDs.
Athena can pair v3 labels with snapshots by URL and time. See [the pairing query](../../../docs/internal/session-replay-structured-data-index.md#pairing-labels-with-snapshots).
Deletion does not remove v3 index rows. It makes the recording blocks that they point to unreadable, as [Data layout and readers](#data-layout-and-readers) describes.

Use the real team ID to exclude all teams present in the model's training data before selecting eval examples.
The exclusion must cover every training month, not only the eval partition's month.
For v2, use the encrypted reader for index entries. For v3, read the Parquet columns directly.
Then fetch selected recording blocks to inspect their JSON-LD payloads.
Legacy v1 indexes retain their pseudonymized identifiers and daily partitions.

### Deletion worker isolation

The deletion task uses the `ai_research_privacy` Celery queue.
In prod-us, only the dedicated `ai-research-privacy-worker` deployment consumes this queue.
Its service account has a dedicated IAM role and cloud-database user.
The database user needs SELECT and UPDATE only on `posthog_aitrainingdeletionrequest`.
The worker starts with `bin/docker-worker-ai-training-privacy` and does not use shared Django signing secrets.
Its process-local signing key is not used for application requests.
The worker skips general migration checks; the outbox table must exist before deployment.
All processes that enqueue deletion work, including the general-purpose Temporal worker, need a key table setting: `AI_RESEARCH_REPLAY_KEY_TABLE` for v3 or `AI_RESEARCH_V4_KEY_TABLE` for v4. Either one turns queuing on.
Shared Django and Temporal workers cannot delete keys from the key table.

## v4 dataset

The recorder reads the Kafka key and headers of each message before it reads the payload.
It records a message only when every check passes, in this order:

1. The session passes the gate below.
2. Capture set the `token`, `session_id` and `distinct_id` headers.
3. No event ingestion restriction for `session_recordings` drops the message, as in the main lane.
4. The team records sessions, has a valid retention period, and its organization opts in to AI training.
5. The session ID is a recent UUIDv7, as in v3.
6. The recorder's own new-session limit did not block the session, as described below.

The recorder reads the team list from Postgres every five minutes.
A refresh that takes more than 60 seconds fails.
After 20 failed refreshes in a row it admits no team until a refresh succeeds, so an opt-out is never ignored for long.
It also admits no team when its list is older than 20 refresh intervals plus their timeouts, whatever the refresh task does.
It consumes the replay topic and its overflow topic.

### New-session limit

The recorder protects the dataset from floods of new sessions with the main lane's rules, applied by itself.
It does not read the main lane's or the v3 mirror's blocklist.

- A session is new when the recorder has neither seen it nor blocked it.
- Each new session from the replay topic takes one token from its team's token bucket. A session that gets no token is blocked as a whole, and the recorder drops every later message of it from both topics.
- A new session from the overflow topic takes no token. The recorder only counts it, as the replay overflow lane does.
- The bucket holds `AI_RESEARCH_V4_NEW_SESSION_BUCKET_CAPACITY` tokens (default 3000) and refills at `AI_RESEARCH_V4_NEW_SESSION_BUCKET_REPLENISH_RATE` per second (default 300), the main lane's production values. Both scale with the sample percentage, because the limit counts only sessions that pass the gate. With `AI_RESEARCH_V4_NEW_SESSION_BLOCKING_ENABLED` set to false, the recorder counts and blocks nothing.
- Each pod keeps its own buckets in memory, as the main lane does, so two deployments block slightly different sessions.
- Seen and blocked sessions are stored in v4's own Redis, `ai-research-v4` (`AI_RESEARCH_V4_REDIS_URL`), not in the primary replay Redis, under `@posthog/ai-research-v4/`. They have the main lane's expiry, so a block survives a restart or a rebalance.
- That Redis evicts the least recently used keys under memory pressure. An evicted seen key makes its session take a second token, and an evicted blocked key lets its session through, so both fail open.
- A Redis error lets the session through, as in the main lane.

### Gate

```text
id         = lowercase(session_id) if it has the UUID shape, else session_id
hash       = md5(id) as lowercase hex
value      = integer of the first 8 hex digits
percentage = (value % 10000) / 100
include    = percentage < AI_RESEARCH_V4_SAMPLE_PERCENTAGE
```

- A percentage of 100 or more includes every session, and 0 or less includes none. The default is 0.
- The gate is the same function as the session feature recorder's rollout gate, so at the same percentage the two lanes select the same sessions.
- Capture keys every replay message with the session ID, so the recorder applies the gate to the Kafka key before it reads the payload.
- Capture keeps the session ID as the SDK sent it. The replay lanes lower-case an ID with the UUID shape (8-4-4-4-12 hex digits), so the gate does too, and every casing of one session gets the same verdict.
- Raising the percentage keeps every session that a lower percentage includes.

### Keys

v4 copies the v3 key design: one key per team and UTC month, and one key per session.

| Row            | `pk`                       | `sk`                   | Attributes                                                                          |
| -------------- | -------------------------- | ---------------------- | ----------------------------------------------------------------------------------- |
| Team month key | `team:{team_id}`           | `month:{YYYY-MM}`      | `team_id` (N), `key_month` (S), `wrapped_key` (B), `expires_at` (N)                 |
| Session key    | `team:{team_id}:shard:{n}` | `session:{session_id}` | `team_id` (N), `key_month` (S), `sealed_key` (B), `key_nonce` (B), `expires_at` (N) |

- `n` is the v3 shard: the first 8 hex digits of `sha256(session_id)` as an integer, modulo 32.
- `key_month` is the UTC month in which the recorder first stored data for the team or session. A session keeps its key in later months.
- KMS wraps a team month key with the encryption context `{"purpose": "ai-research-v4", "team_id": ..., "key_month": ...}`.
- A session key is sealed under the team month key with HKDF-SHA256 (empty salt, info `ml-session-key-wrap`) and AES-256-GCM. The additional authenticated data is the canonical JSON of `{"key_month", "purpose": "ai-research-v4", "session_id", "team_id"}`.
- `expires_at` is the start of the fifth month after `key_month`, in epoch seconds: key month 2026-10 expires at 2027-03-01. DynamoDB TTL removes the row after that. A session writes for at most about 15 days after its key month ends, and an object lives at most 38 days, so every key outlives the objects that use it. The margin lets the object windows go back up to 90 days without a change to the key expiry.
- A row past `expires_at` that DynamoDB has not removed yet is not used.
- Writers store keys before the objects that use them, as in v3.
- Only the recorder creates keys. The image fetcher only reads them, and it drops a job whose team month row is missing or deleted.

The recorder derives two more keys from the team month key with HKDF-SHA256 and an empty salt:

- The image content key, with info `ml-image-content-key`, keys the HMAC of an inline image.
- The image URL key, with info `ml-image-url-key`, keys the HMAC of a remote image URL.

Image and URL references therefore stay the same for a whole month, and cannot be compared across teams or months.

### Deletion

v4 uses the v3 deletion outbox and worker. The same team, recording and person deletion requests shred v4 keys.
The worker shreds v4 keys only when `AI_RESEARCH_V4_KEY_TABLE` is set, and a request completes only when every configured key table is done.
It keeps its v4 progress under its own cursor key, `v4_work`.
It writes a tombstone and never removes a row:

```text
UpdateItem  SET deleted = :true, expires_at = if_not_exists(expires_at, :expiry) REMOVE wrapped_key, sealed_key, key_nonce
```

| Request                                  | The worker tombstones                                                                                                                         | Unreadable after the key caches expire                                                                    |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Session, and person through its sessions | The session row                                                                                                                               | The session's blocks and its sealed index values. Its `url_fingerprints` can no longer be linked to a URL |
| Team                                     | The team month rows of the previous, current and next UTC month, then every `month:` row of the team, then every session row in the 32 shards | Everything of the team: blocks, inline images, fetched images and sealed index values                     |

- A session tombstone does not reach inline or fetched images. Both are sealed under the team month key, and other sessions of the team can refer to the same image. They stay readable with that key until they expire (see [Lifecycle](#lifecycle)), but the deleted session's blocks, which say where the session used them, cannot be read.
- A tombstone the worker creates for a row that does not exist yet gets an `expires_at` by the key rule, from the row's month for a team month row and from the current month for a session row. A tombstone that replaces a key keeps the key's expiry.
- The worker reads only `pk` and `sk` and has no KMS access. Its role has Query and UpdateItem on the v4 key table.
- A conditional put cannot replace a tombstone, so no writer creates a new key for a deleted row. A writer that meets a tombstone drops the data, and the image fetcher drops a job whose team month row is deleted.
- A process that already holds a key can use it until its cache entry expires: 5 minutes for a session row, one hour for a team month row. What it writes in that time stays unreadable, because the stored row no longer holds the key.
- v4 has no month deletion. `delete_ai_training_month` shreds v3 keys only, and v4 objects expire on their own (see [Lifecycle](#lifecycle)).
- Deletion does not remove index rows or the plaintext columns in them. They expire with the bucket lifecycle.

### Lifecycle

Nothing in v4 is kept for good. Each kind of data has a fixed lifetime, and a deletion only makes data unreadable sooner.

| Data                           | Where                                                            | Lifetime                                                                                                                           | Removed by                    |
| ------------------------------ | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| Session blocks                 | `rrweb-v4` `blocks/`                                             | 30 days after the write                                                                                                            | S3 expiration                 |
| Block and image index          | `rrweb-v4` `index/`                                              | 30 days after the write                                                                                                            | S3 expiration                 |
| Inline image packs             | `images-v4` `images/packs/`                                      | 38 days after the write                                                                                                            | S3 expiration                 |
| Fetched images                 | `images-v4` `images/url/`                                        | 38 days after the last write. The fetcher copies an image onto itself when a job refers to it and the copy is more than 7 days old | S3 expiration                 |
| Team month and session keys    | `ai-research-replay-v4-keys`                                     | Until the start of the fifth month after `key_month`                                                                               | DynamoDB TTL                  |
| Tombstones                     | `ai-research-replay-v4-keys`                                     | The same expiry as the row they replace                                                                                            | DynamoDB TTL                  |
| Fetch history and robots cache | `ai-research-v4-image-fetch-history`                             | URL history: 8 days after the end of its month. Robots and tdmrep cache: at least 30 days                                          | DynamoDB TTL                  |
| Index records                  | Kafka `ai_research_v4_index`                                     | 7 days                                                                                                                             | Topic retention               |
| Fetch jobs, with raw URLs      | Kafka `ai_research_v4_image_fetch`, its retry topics and its DLQ | 24 hours                                                                                                                           | Topic retention               |
| Seen and blocked sessions      | `ai-research-v4` Redis, `@posthog/ai-research-v4/`               | The main lane's expiry, or earlier under memory pressure                                                                           | Redis expiry and LRU eviction |
| Held keys                      | Recorder and fetcher memory                                      | 5 minutes for a session row, one hour for a team month row                                                                         | Cache expiry                  |

- S3 expiration counts from the time an object was written, rounds up to the next midnight UTC and can run late, so plan for objects to stay for up to 2 days more.
- Blocks expire by write time, not by session start, so a session whose blocks span several write days loses its first blocks first. Nothing marks the rest as partial, and `cold_start` does not cover it. Readers that need whole sessions follow the rule in [Block index](#block-index).
- The buckets have no versioning, so an expired object leaves no older version behind. S3 removes the parts of an unfinished upload after one day.
- `blocks/` is stored in Glacier Instant Retrieval from the start. The index prefixes and both image prefixes stay in Standard, because readers read them often.
- A block can use an image only while the image outlives the block. A pack is written in the same flush as its blocks and expires 8 days later. A fetched image lives at least 30 days after the last block that refers to it, because the recorder sends a job for each referenced URL at least once per day.
- A key outlives every object it sealed: a session writes for at most about 15 days after its key month ends, and an object lives at most 38 days plus the S3 delay. The margin lets the object windows go up to 90 days without a change to the key expiry. Raise the object windows in `v4-staging.hcl` in posthog-cloud-infra only together with the key expiry.
- DynamoDB TTL can remove a row days after `expires_at`. Writers and readers treat a row past `expires_at` as unusable, so the delay only costs storage.
- The key table has no point-in-time recovery, backups, exports, streams or replicas, so no copy brings a shredded key back.

### Envelope

v4 objects use the v3 `AISR03` frame.
The additional authenticated data is the canonical JSON of `{"v": 4, "context": ...}`, so a v3 reader never opens a v4 object.

| Object                 | Key            | `context`                                                                                           |
| ---------------------- | -------------- | --------------------------------------------------------------------------------------------------- |
| Session block          | session key    | `teamId`, `sessionId`, `keyMonth`, `kind: "rrweb"`, `codec: "brotli"`, `ref` (the block object key) |
| Inline image in a pack | team month key | `teamId`, `keyMonth`, `kind: "image"`, `codec: "none"`, `ref` (the image reference)                 |
| Fetched image          | team month key | `teamId`, `keyMonth`, `kind: "image-url"`, `codec: "none"`, `ref` (the image URL reference)         |
| Sealed index value     | session key    | `teamId`, `sessionId`, `keyMonth`, `kind: "index"`, `ref` (the column name)                         |

A sealed index value uses the v3 JSON envelope with `"v": 4`.
`nodejs/src/ingestion/pipelines/sessionreplay/ai-research/v4-keys/encryption-vector-v4.json` pins one frame of each sealed object kind, so a reader in another language can check its own bytes.

### Blocks

A block holds the replay messages of one session from one Kafka partition in one flush, as JSON lines of `[window_id, event]`, compressed with Brotli at quality 9 and a 22-bit window, as in v3.
The recorder streams each block into the encoder. Read a block as a stream: a Brotli stream does not state its decompressed size.

- posthog-js compresses some fields of an event and marks the event `cv: "2024-10"`. The recorder expands those fields to plain JSON and removes the `cv` key, as the replay player does, because the gzip strings do not compress again. An event that does not decode stays exactly as it arrived.
- An inline image becomes `image:v4:{team_id}:{YYYY-MM}:{hash}` in the block, where the month is the UTC month of the write.
- The recorder takes base64 PNG, JPEG, GIF and WebP data URIs in any letter case and with parameters, under the v3 size limits. The image bytes name the format, not the data URI's label, so the image index `mime` is always one of these four. A data URI whose bytes have none of their signatures stays inline, for example a font labeled `image/ttf`, an icon or an empty payload.
- The dataset keeps no AVIF image. A base64 data URI that its label or its bytes name as AVIF becomes `image:v4:declined:avif`, and a srcset loses such a candidate. The recorder counts these as `ai_research_v4_recorder_removed_images_total{format="avif"}`. A payload broken by an escape the scan does not read stays inline. It also takes the image frames of the posthog-js canvas recorder. Anything else stays inline in the sealed block, for example SVG or line-wrapped base64.
- A remote image URL becomes `imageurl:v4:{team_id}:{YYYY-MM}:{hash}` in the block and in its fetch job, where the month is the UTC month of the write. The block and the job always carry the same reference, so a reader opens the fetched image directly.
- A URL that the URL policy refuses becomes `imageurl:v4:declined:{reason}` in the block, for example `declined:credential`, `declined:non_public_host` or `declined:tracking_beacon`. The original URL cannot be recovered. The recorder counts rewrites and refusals in `ai_research_v4_recorder_image_url_rewrites_total`.
- The rewrite covers every remote URL that the recorder reads from an image slot: image sources, `srcset`, SVG image links, video posters, `<picture>` sources and CSS `url(...)` in style attributes, style sheets and style rules. It also covers `src`, `srcset`, `href` and `poster` in an attribute change on a node the recorder does not know, for example after a restart. `srcset` keeps its descriptors and CSS keeps its `url(...)` syntax. It is not limited by the 512 URLs per message that get fetch jobs.
- A srcset in an image slot keeps only the candidates the recorder stores. A candidate the URL policy refuses leaves the list instead of becoming a `declined` marker, and the rest keep their descriptors. A `<picture>` source whose `type` names a media type the image fetcher does not store, such as `image/avif`, gets no fetch job and loses its remote candidates, unless a source of a stored type names the same URL. Its inline images, such as SVG data URIs, stay. The writer rebuilds each srcset that the inspector read in an image slot, in the bytes it stores, after the inline images left and the escapes were written again. It separates the candidates with a comma and a space. A `srcset` key elsewhere, for example in a custom event's payload, stays as it is. A browser skips a source with no candidates, so the replay falls back to the next source or the `img`. The recorder counts these as `ai_research_v4_recorder_srcset_rewrites_total{outcome="trimmed"|"emptied"}`.
- The recorder reads a protocol-relative URL, such as `//cdn.example.com/a.png`, as `https`. It gets the same reference or `declined` marker as the `https` form, and the rewrite replaces the text as the block holds it. A browser reads a backslash as a slash there, so `\\cdn.example.com/a.png` counts too, and so does a URL such as `https:\\cdn.example.com/a.png` with any mix of slashes and backslashes after the scheme, or none: on a page of another scheme the browser loads `https:cdn.example.com/a.png` from that host.
- Some URLs stay as they arrived: relative URLs, remote URLs outside image slots (links, frames, text, CSS custom properties and other CSS properties), the `image-set()` candidates the recorder does not choose, URLs inside a compressed value that did not decode or that the decode budget skipped, and URL text written in another form than the recorder read it, for example with a CSS escape. The recorder counts the last kind as `outcome="unrewritten"`.
- Before the rewrite, the recorder writes again any JSON string that holds an escape capture would not write, for example `\/`, so an escaped URL is found too. A scheme matches in any letter case.
- If a refused URL is still in a block after the rewrite, the recorder writes the block again instead of dropping it. The second pass replaces the refused URL wherever its bytes are, also inside a longer URL. For a refused URL the stored bytes do not hold as the recorder read it, for example behind a CSS escape, it replaces every URL token that holds the URL's host with `imageurl:v4:declined:unchecked`. The recorder counts this as `url_fallbacks_total{reason="declined_kept"|"declined_unfound"}`. It drops the block, as `dropped_blocks_total{outcome="declined_unrewritten"}`, only when the second pass still leaves a refused URL, so no refused URL is stored.
- The recorder reads object keys as the player does: it writes an escaped key, such as `"\u0073rc"`, in its plain form before it inspects the event, and it takes the last copy of a repeated key.
- A block that the recorder cannot check in full is kept. Past 10,000 image-slot URLs (`too_many_urls`), 2 MiB of them (`too_many_url_bytes`) or 200,000 attribute changes in a mutation (`too_many_attribute_items`), the recorder names the URLs it read, and replaces every other remote URL token in the block, links and text included, with `imageurl:v4:declined:unchecked`. A replaced token runs to whitespace or the end of its JSON string, and to the `)`, `'` or `"` that ends a CSS URL, so the scrub never splits an escape. It counts these as `url_fallbacks_total{reason}` and the replaced tokens as `scrubbed_urls_total`. A URL of any length is named; one longer than the fetcher takes becomes `imageurl:v4:declined:too_long`. Only a block whose sealing fails is dropped.
- When the text of a rewritten URL also appears outside an image slot in the same block, it is replaced there too.
- `hash` is the first 22 characters of the base64url HMAC-SHA256, as in v3.

### Layout

Every prefix that the recorder writes is partitioned by the UTC day of the write.
Fetched images are partitioned by the key month of their reference.

| Bucket      | Prefix                                        | Contents                                                                        |
| ----------- | --------------------------------------------- | ------------------------------------------------------------------------------- |
| `rrweb-v4`  | `blocks/dt={day}/`                            | One object per recorder flush: sealed blocks, each found by byte range          |
| `rrweb-v4`  | `index/blocks/dt={day}/`                      | Parquet, one row per block                                                      |
| `rrweb-v4`  | `index/images/dt={day}/`                      | Parquet, one row per stored inline image                                        |
| `rrweb-v4`  | `index/blocks/_watermarks/`                   | JSON, one object per Kafka partition: how far the block index is complete       |
| `rrweb-v4`  | `index/images/_watermarks/`                   | JSON, one object per Kafka partition: how far the image index is complete       |
| `images-v4` | `images/packs/dt={day}/{team_id}/`            | One object per recorder flush and team: sealed images, each found by byte range |
| `images-v4` | `images/url/month={YYYY-MM}/{team_id}/{hash}` | One sealed fetched image per URL reference                                      |

S3 expires every object a fixed time after it was written: 30 days in `rrweb-v4` and 38 days in `images-v4`. [Lifecycle](#lifecycle) lists every lifetime and why they fit together.

The recorder does not write the two index prefixes itself, as in v3:

- After a flush stores its packs and blocks, the recorder sends one JSON record per index row to `ai_research_v4_index`. The record's keys are the Parquet column names.
- The recorder commits without waiting for delivery. A row that is not delivered leaves its block or image stored but not in the index.
- The v4 Parquet sink reads the topic, groups the rows by index and write day, and writes one file per group and flush as `{ms}-{random}.parquet`. A flush runs every 10 minutes, or at 128 MiB of rows or 1,000,000 rows. The sink commits its offsets only after the files are stored.
- Index files use four column types: `INT32`, `INT64`, `UTF8` and `BOOLEAN`. Integers are signed. The recorder caps an `INT32` value at the type's range and an `INT64` value at ±(2^53 − 1), so every value is a safe JavaScript integer. It ignores an event timestamp outside the JavaScript date range. Byte counts, offsets and times are `INT64`, the other counts `INT32`. `moments` is a 3-level `LIST` (`moments`, then the repeated group `list`, then the struct `element`), so Athena, Arrow readers and DuckDB see a non-null list of structs. Files written before the sink used that layout hold `moments` as a bare repeated group whose item is named `moments`. Arrow readers and DuckDB read those as the same list of structs, but Athena reads the column as null, because Trino reads a bare repeated group of more than one field as a missing column. Those files expire with the bucket's lifecycle. `url_fingerprints` and `window_ids` are lists of `UTF8` with no null items. The three [surfacing](#surfacing-features) sets are nullable 3-level `LIST`s of `UTF8` or `INT64` with no null items. Row groups hold 131072 rows, and every column is zstd-compressed at level 9. Older files can still be snappy-compressed and in arrival order until they expire; Parquet records the codec per column chunk, so a reader handles both. The sink writes no statistics for `urls`, because a sealed value has no useful order.
- The sink can write a row twice after a restart. The copies have the same `flush_id`, so the rule below does not remove them: readers first drop rows that repeat within one `flush_id`.

### Block index

A flush can write its blocks and index rows and then fail before it commits its Kafka offsets.
The next attempt for that partition starts at the same committed offset and writes the same messages again.
A retry can also cover a different range than the attempt it replaces, for example one flush that replays two earlier flushes.
Every row therefore names its flush and its Kafka position.
The index rows are published without waiting for delivery, so a retry can also reach the index only in part.
Every row of one (`flush_id`, `topic`, `partition`) carries the same `flush_end_offset` and `flush_row_count`, and its own `flush_row_index` from 0.
Readers drop duplicates with one rule per (`topic`, `partition`), applied to all rows before any session or team filter:

1. Drop rows that repeat a (`flush_id`, `flush_row_index`).
2. Call a flush complete when it has `flush_row_count` distinct rows. Give each flush the range from its `start_offset` to its `flush_end_offset`.
3. Walk the complete flushes from the highest (`flushed_at_ms`, `flush_id`) to the lowest, and keep a flush only if its range does not overlap the range of a flush already kept.
4. Then walk the incomplete flushes in the same order, with the same overlap check. A kept incomplete flush is best effort: some of its blocks are missing from the index, but the blocks it lists are valid.

A flush keeps or loses its whole range. When two flushes overlap, the reader keeps only the one it reaches first, even when their ranges differ in size, so it never merges parts of two flushes.

Each file holds its rows in (`team_id`, `session_id`, `first_ts_ms`) order, with a null `first_ts_ms` last, so the blocks of a session in one file are adjacent and in time order.
The order holds only within a file. The blocks of a session spread over many files and write days, and a file is usually one row group, so its min and max statistics do not narrow a lookup.

A reader that needs whole sessions selects them by the start time in the session UUIDv7, not by write day:

- Read the write days from the UTC day of `start - 1 day` onward. The recorder admits a session from 1 day before its start until 14 days after it, so no block of a session has an earlier write day.
- Use a session only while its start is less than 29 days old. Every block lives at least 30 days after its write, so until then no block has expired.
- A session can get more blocks until its start is 14 days old. A reader that needs final sessions uses only sessions with a start between 14 and 29 days old.

A session row is a fold over its block rows: sort them by `first_ts_ms`, then merge each into the result in order.
Counts sum, times take the minimum or maximum, flags take the logical or, `host` takes the first value and the viewport takes the one with the highest `viewport_ts_ms`.
The DOM sizes `dom_nodes` and `dom_text_chars` and `max_written_event_bytes` take the maximum, because they describe a state or a single event, not an amount.
`url_fingerprints` and `window_ids` take the ordered union, capped at 10 and 32 entries. A session at the cap has that many or more.
The [surfacing](#surfacing-features) sums add, its two maxima take the maximum, and its three sets take the union with no cap.
The flush columns describe a row, not a session, so the fold does not carry them.
`events_before_first_full_snapshot` sums, because the recorder stops counting it once the session has a decoded full snapshot.
`max_gap_ms` also counts the gap between one block's last event and the next block's first event. When blocks overlap, for example the main and overflow topics, it is an upper bound.
`active_ms` is the active time that a block's events add to the session.
The recorder runs the segmentation of `segmentation.ts` over the whole session, not over one block, so the blocks sum to the session's active time wherever the flushes cut it.
Blocks that overlap in time, such as main and overflow blocks in one flush, do not count the same time twice.
A block's `active_ms` can include time before its first event when the block continues an active segment of an earlier block.
This holds for the blocks that one recorder process inspected. After a rebalance or a restart, up to 5 seconds of a segment that spans the handover is lost. When two processes record overlapping parts of one session, the overlap can count twice.
`fold_session` in `replay-core-v4` implements this fold.

| Group       | Columns                                                                                                                                                                                                                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Location    | `team_id`, `session_id`, `key_month`, `block_s3_key`, `block_byte_start`, `block_byte_end`                                                                                                                                                                                                 |
| Kafka       | `topic`, `partition`, `start_offset` (the flush's first offset on the partition), `end_offset` (the block's last offset), `flush_end_offset` (the last offset the flush covers), `flush_id`, `flushed_at_ms`, `flush_row_count`, `flush_row_index`                                         |
| Time        | `first_ts_ms`, `last_ts_ms`, `event_count`, `byte_size`, `written_jsonl_bytes`, `max_written_event_bytes`                                                                                                                                                                                  |
| Source      | `snapshot_source`, `snapshot_library`, `host`                                                                                                                                                                                                                                              |
| Playability | `full_snapshots`, `events_before_first_full_snapshot`, `orphan_mutations`, `max_gap_ms`, `dom_nodes`, `dom_text_chars`, `remote_stylesheets`, `inline_stylesheets`, `iframes`, `canvases`, `videos`, `shadow_roots`, `cold_start`, `node_cap_reached`, `decode_failures`, `window_ids`     |
| Activity    | `active_ms`, `clicks`, `mouse_interactions`, `rage_clicks`, `dead_clicks`, `keypresses`, `scrolls`, `mouse_moves`, `touches`, `touch_moves`, `selections`, `media_events`, `viewport_resizes`, `navigations`, `console_errors`, `console_warnings`, `network_requests`, `network_failures` |
| Context     | `viewport_width`, `viewport_height`, `viewport_ts_ms` (the time of the viewport event), `touch_input`                                                                                                                                                                                      |
| Images      | `images_extracted`, `image_bytes`, `images_inline`, `image_urls`                                                                                                                                                                                                                           |
| Moments     | `moments`: a list of `{kind, window_id, ts_ms, event_index}` for full snapshots, navigations, clicks and large DOM changes, and `moments_truncated`                                                                                                                                        |
| Sealed      | `urls`: the visited URLs as a sealed index value, `urls_truncated`, and `url_fingerprints`                                                                                                                                                                                                 |
| Surfacing   | The `surfacing_` columns: what ingestion's surfacing feature recorder records for the block as one batch. See [Surfacing features](#surfacing-features)                                                                                                                                    |

- `full_snapshots` counts only snapshots that decoded.
- `events_before_first_full_snapshot` counts the session's events before its first decoded full snapshot.
- `host` is the host of the first page URL. An IP-address host is stored as `[ip_address]`, as v3 does, and a host longer than 253 bytes is stored as null.
- `navigations` counts URL changes from Meta events and from posthog-js `$url_changed` events, so single-page apps count too.
- `node_cap_reached` is true when the recorder could not check a window for orphan mutations: the window passed the node cap, a snapshot or mutation did not decode, the window was evicted and came back, or the recorder dropped the session's DOM state to stay within its memory budget.
- `byte_size` counts the event bytes as they arrived. `written_jsonl_bytes` counts the block's lines as the recorder wrote them, after it expanded compressed values and removed images, and before Brotli. `max_written_event_bytes` is the longest of those lines. Use these two for memory and size limits.
- `mouse_interactions` counts every mouse interaction event, of every type. `clicks` counts only clicks. `touch_moves` counts touch move events; `touches` also counts touch starts and ends.
- `decode_failures` counts, once per event, a compressed value that did not decompress or that the decode budget skipped, a full snapshot the recorder could not decode or walk, a mutation that did not decode or held a node too deep to walk, and a style sheet rule whose compressed value failed. A message that did not read at all reaches no block, so this column does not count it. A block with failures has activity and DOM columns that can be too low.
- `moments` are hints for where to look, not checked baselines. A `full_snapshot` moment means the recorder decoded that snapshot. `full_snapshot_undecoded` marks an event tagged as a full snapshot that it did not decode. The list keeps the first 256 moments, and `moments_truncated` is true when it dropped more.
- `window_ids` lists the distinct window IDs of the block's events, the same IDs as in `moments`.
- `urls` holds at most 100 page URLs of up to 2 KiB each and 32 KiB in all. `urls_truncated` is true when the recorder left pages out.
- `url_fingerprints` holds up to 10 distinct page URLs of the block as the first 16 hexadecimal characters of an HMAC-SHA256 of the URL. The key is derived from the session key with HKDF-SHA256, empty salt and info `ml-url-fingerprint-key`, so fingerprints can be compared only within one session. They count distinct URLs, where `navigations` counts URL changes.
- `cold_start` is true when the recorder first sees a session after it started, for example after a partition rebalance, or after it dropped the session's DOM state to stay within its memory budget. Its playability columns then describe only the part of the session the recorder saw.

#### Surfacing features

The `surfacing_` columns let a sampler score whole sessions with the surfacing booster without opening a block.
Each block row holds what ingestion's `SessionFeatureRecorder` (`session-feature-recorder.ts`) records for one batch, and the recorder computes it with the same definitions.
Its state starts again at each block, as ingestion's does at each batch: a block is one session's events from one Kafka partition in one recorder flush, as a batch is.
After the prefix, each column has the name of the `session_replay_features` column it matches, with a unit for the sums that are not counts.
A session's values are the fold of its block rows, as `_AGGREGATED_STATS_FRAGMENT` (`posthog/temporal/session_replay/surfacing_scoring_sweep/sql.py`) folds the batch rows, and `fold_session` in `replay-core-v4` implements it.

| Kind   | Columns                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Counts | `INT32`: `surfacing_{name}_count` for the 31 counters of `session_replay_features`, from `event_count` to `selection_copy_count`, and `surfacing_{token}_path_visit_count` for the 14 path tokens, where `404` is `not_found`                                                                                                                                                                                                                                                                                                           |
| Sums   | `INT64`: `surfacing_mouse_sum_x_millipx`, `surfacing_mouse_sum_y_millipx`, `surfacing_mouse_sum_x_squared_px2`, `surfacing_mouse_sum_y_squared_px2`, `surfacing_mouse_distance_traveled_millipx`, `surfacing_mouse_velocity_sum_px_per_s`, `surfacing_mouse_velocity_sum_of_squares_px2_per_s2`, `surfacing_total_scroll_magnitude_millipx`, `surfacing_inter_action_gap_sum_ms`, `surfacing_inter_action_gap_sum_of_squares_ms2`, `surfacing_network_request_duration_sum_us`, `surfacing_network_request_duration_sum_of_squares_ms2` |
| Maxima | `INT64`: `surfacing_max_scroll_y_millipx`, `surfacing_max_idle_gap_ms`                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Sets   | `surfacing_visited_url_fingerprints` (`UTF8`), `surfacing_click_target_ids` and `surfacing_form_field_ids` (`INT64`)                                                                                                                                                                                                                                                                                                                                                                                                                    |

- Ingestion stores a float sum as a double. The index stores it as an integer in the unit at the end of its name, rounded once per block, so that a fold is exact in any order. `millipx` is 1/1000 of a pixel and `us` is a microsecond. Ingestion's mouse velocity is in pixels per millisecond, so `surfacing_mouse_velocity_sum_px_per_s` is 1000 times its sum and `surfacing_mouse_velocity_sum_of_squares_px2_per_s2` 1000000 times its sum of squares.
- The sets hold distinct values, sorted. The click targets and form fields are rrweb node IDs. The visited pages are fingerprints in the format of `url_fingerprints`, under the same key: ingestion stores an md5 of each URL instead. Each set keeps the first 1000 values of a block, as ingestion keeps 1000 per batch. The sweep counts a set with `uniqCombinedMerge(12)`, and the length of the folded set is the exact count.
- A page URL is the trimmed `data.href`, or else `data.payload.href`, of any event, as `hrefFrom` in `rrweb-types.ts` reads it. The path token counts compare the segments of its path with a fixed list of words, so they hold no other part of a URL.
- The recorder skips an event without a positive timestamp, which ingestion's parse step drops before its recorder. The booster's rates divide by the session duration, which a sampler takes from `first_ts_ms` and `last_ts_ms`. Those also count events with a timestamp of zero or less.
- The columns are null in a row from a recorder that predates them, and absent from files written before them. A sampler falls back to the session's live score for such a session.
- Ingestion corrects the event times of a message by the sender's clock skew, rounded to 5 minutes, and the recorder does not. A block whose messages got different corrections can therefore differ in its time-based values.
- A field of an unexpected JSON type counts as missing, where JavaScript can coerce it or produce NaN, for example a mouse position without coordinates. Ingestion's parse step lets such fields through.

#### Watermark files

After a flush, the sink writes one JSON file per index and Kafka partition of `ai_research_v4_index`, so a reader can learn from the bucket how far the index is complete:

- `index/blocks/_watermarks/partition={NNNN}.json` for block rows.
- `index/images/_watermarks/partition={NNNN}.json` for image rows.

`{NNNN}` is the partition number with four digits, for example `partition=0007.json`.
Each file holds one object:

| Field                       | Meaning                                                                                                                                                                                                                                                                                  |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `partition`                 | The Kafka partition.                                                                                                                                                                                                                                                                     |
| `complete_up_to_capture_ms` | Every row that the sink read from the partition with an earlier capture time is in an index file in S3. It is the value of `ml_replay_capture_watermark_timestamp_seconds` for the partition, in milliseconds: `data="event_metadata"` for blocks and `data="inline_images"` for images. |
| `committed_offset`          | The next offset to read on the partition. The sink stored it for commit after it wrote every row below it.                                                                                                                                                                               |
| `written_at_ms`             | When the sink wrote the file.                                                                                                                                                                                                                                                            |

The capture time of a row is the Kafka timestamp of the replay record that it came from, which the recorder sends in the `capture-timestamp-ms` header.
The sink writes a file only for a partition that it still owns, and only after a flush wrote the partition's rows and stored its offset.
A row that the sink holds but has not written keeps the value at or below its capture time.
The sink rewrites its files once every `WATERMARK_FILE_INTERVAL_MS` (`index-watermark-files.ts`), on the first flush or poll after the interval, also when no rows arrive.
A value can rise without new rows, because the watermark also counts the rows that it finished in the last `FINISHED_WINDOW_MS` (`capture-watermark.ts`).
Each write is a plain PUT that replaces the file.
A failed write does not fail the flush. The sink counts it in `ai_research_v4_parquet_sink_watermark_writes_total`, logs it, and writes the file again after the next interval. A write that the sink aborts because it lost the partition counts as `outcome="cancelled"`.
S3 expires a file 30 days after its last write, as it does every object in the bucket.

To learn how far an index is complete, a reader:

1. Reads every file under that index's `_watermarks/`.
2. Takes the minimum `complete_up_to_capture_ms` across the partitions.
3. Treats a file whose `written_at_ms` is more than about 15 minutes old as a partition that is not progressing: no sink writes it. Its value is still true, but it does not move. A running sink keeps each file it owns at most the rewrite interval plus one poll old.

Some limits apply:

- A partition that delivers no records keeps its last value, as the gauge does, and the sink keeps rewriting its file. So a quiet partition holds the minimum down.
- When the sink loses a partition, it aborts the partition's watermark writes that are still in flight, retries included. A write that S3 already received can still land. The new owner writes its first file only after its first flush, so the two overlap only if S3 takes longer to apply that write than the new owner takes to flush. The file then holds an older value until the new owner writes again. That value is still true. A full fence is not possible, because the bucket does not let the sink read the file that it replaces.
- A partition that the sink has not flushed since it started to write these files has no file. A reader that needs every partition compares the number of files with the partition count of the topic.
- The value covers only the rows that reached the sink. The recorder sends a row only after its own flush stores the block or image, so a row with an earlier capture time can still be in the recorder. A sink that has read all of its topic does not make the index complete.
- A reader that lists `index/blocks/` or `index/images/` for Parquet files must skip `_watermarks/`. Hive-style readers such as Spark, Athena and pyarrow datasets ignore paths that start with `_`, and a `*.parquet` glob does not match the JSON files.

### Image index

`index/images/` has one row per inline image in a pack: `team_id`, `key_month`, `image_ref`, `pack_s3_key`, `byte_start`, `byte_end`, `mime` and `byte_size`.

- Each frame in a pack is sealed under the team month key of the write month, as a fetched image is. A session deletion therefore does not make inline images unreadable (see [Deletion](#deletion)).
- `image_ref` uses the team month image content key, so the same image has the same reference in every session of the team month. A pack holds one frame per distinct reference, so an image that two sessions show in one flush is stored once. A later flush stores it again.
- A reader resolves an image of a block by (`team_id`, `image_ref`) and opens it with the team month key of `key_month`.
- The sink writes [watermark files](#watermark-files) for this index too, under `index/images/_watermarks/`.

### Remote images

The recorder sends each remote image URL that the URL policy accepts to the `ai_research_v4_image_fetch` topic in the v3 job shape, keyed by registrable domain. The job carries the reference that replaces the URL in the block.
It collects URLs from image sources, `srcset`, SVG image links, CSS `url(...)` values and attribute mutations, and skips hidden or 1×1 images as v3 does.
The topics hold jobs for 24 hours, because jobs carry raw URLs.
The v4 image fetcher is its own copy of the v3 fetcher under `ai-research/image-fetch-v4/`, with the v3 fetch policy, its own consumer groups, its own `AI_RESEARCH_V4_IMAGE_FETCH_*` settings and a share of the v3 per-host limits. It shares no code or table with v3.
It applies the recorder's URL policy through `@posthog/ai-research-v4-native`, an addon over `replay_core_v4::url_policy`, so it canonicalizes a URL, groups it by registrable domain and refuses private hosts exactly as the recorder does.
It stores each image, sealed and unscrubbed, under `images/url/`, and it does not send images to the scrub lane.
It stores PNG, JPEG, GIF, WebP and SVG as fetched. It does not rasterize an SVG; redaction downstream of the dataset handles SVG text.
The response must have one of these media types and bytes of that format: a signature for a raster image, or an SVG root element for SVG. An SVG may carry a byte order mark, comments, processing instructions and a doctype before its root. The doctype may name no internal subset and no external DTD other than a W3C SVG DTD, so that a parser downstream cannot resolve entities from the document. It refuses AVIF and every other type.

The fetcher keeps a crawl history per URL reference, so per team and month, in its own DynamoDB table `ai-research-v4-image-fetch-history`, with the v3 fetch interval and conditional requests. The table also holds its robots.txt and tdmrep cache:

- The first job for a reference fetches the image from its origin.
- A later job before the v3 refetch time does not contact the origin. When the stored copy is more than 7 days old, the fetcher copies it onto itself. Otherwise it drops the job.
- A job after the v3 refetch time sends a conditional request with the stored `ETag` or `Last-Modified`. A `304` refreshes the stored copy by a copy onto itself, and a `200` replaces it.
- The history item expires 8 days after the end of its month, as v3 history does. A reference carries the month of its write, so no job refers to it after that.
- An item that does not parse, for example one that a newer build wrote, reads as a miss. The fetcher counts it and fetches the image again.
- The history holds no URL in plaintext. It binds the stored validators to an HMAC of the response URL under the team month URL key, and sends them only when the job's URL has the same HMAC.

A URL is therefore fetched from its origin about once per team and month, as v3 fetches it about once in 30 days.
Unlike v3, the history is per team: a sealed image is readable only with its team's key, so two teams that refer to one URL each fetch it.
The recorder sends a job for each referenced URL at least once per day, so the fetcher sees a reference in every 7-day refresh interval.
The fetcher drops a job whose team month row is missing, expired or deleted.
