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
- At or after **Monday, 2026-09-21 at 17:00 UTC** (18:00 in Europe/London): v3 keeps the v2 identifiers and keys, and stores its objects in the v3 buckets under `rrweb_3/` and the `/v3/` dataset paths.
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
A parquet column holds a value and not an object body, so `metadata` and `replay-index` stay JSON with `v`, `context`, `nonce` (12 bytes, base64) and `ciphertext` (the sealed bytes followed by the 16-byte tag, base64). A reader there knows the shape from the column and inspects no magic bytes.
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
A lookup failure stops the request before profile deletion so it can retry.
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

The person lookup matches any available replay row for the requested IDs, then deduplicates and paginates sessions.
It does not filter out recordings marked deleted or past their replay retention date while their index rows remain.
Replay index retention limits this lookup: after those rows expire, person deletion cannot discover the corresponding ML sessions.
New sessions from the same person can be collected if consent permits them.
Team lookups use 32 session shards with strongly consistent DynamoDB queries.
Deleting a resolved session removes all of its events, including events from other identities.

Deletion uses resumable query pages and stores progress in the outbox.
A failed request backs off without blocking unrelated requests.
Completion follows key removal and the five-minute reader lifetime.
Scrubbed images remain available after session or person deletion, but become unreadable after team or month deletion.

This mechanism covers encrypted v2 objects.
It does not erase legacy plaintext objects, previously downloaded data, derived training artifacts, or a trained model.
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
A reader finds the bucket of a block in its `block_url`, and resolves an `image:v3:` or `imageurl:v3:` reference in the v3 images bucket under the `/v3/` paths.

Metadata catalogs expose raw `team_id`, `session_id`, `format_version`, and an encrypted `payload`.
URLs, block locations, and replay indexes are inside that payload.
Neither the catalog nor its encrypted payload includes a distinct-ID field.
V2 does not write a separate plaintext replay index.

Athena can select catalog rows but cannot decrypt replay fields.
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
Kafka records between the ML lanes travel in cleartext; only objects in S3 are sealed, and stored scrubbed images use team image keys.
Consumers reject malformed UUIDv7 session identifiers before reading DynamoDB.
Oversized identifiers cannot fail a whole bulk key lookup.
Inline images have an encrypted lookup for each reference, published after the shard and its index.
Readers fetch that lookup directly; a missing image does not require a scan of the team's image history.
The image scrubber hands the images it scrubbed to a write lane every 30 seconds or when its buffer is full, writes them while it scrubs the next batches, and writes the shard groups of one hand-off concurrently.
The offsets of a hand-off are stored after its writes complete, in hand-off order, so a failed write stops every later store and the pod replays from the last stored offset.
Source deduplication includes the session, so deleting one source session cannot suppress another session's copy.
The v2 image-fetch frontier uses a separate, initially empty DynamoDB history table.
Its URL history expires eight days after the end of the session's UTC month.
Explicit HTTP freshness or cache restrictions can shorten this expiry; they cannot extend it.
Robots.txt and TDM reservation caches keep their shared origin keys and existing expiry rules.
It does not inherit v1 seen flags or successful fetch results.

ML Kafka producers write `ai_research_ingestion_version: 1` or `2`.
Retries and dead-letter replay preserve this header and the record bytes.
Consumers drop records that still use the sealed envelope shape from before cleartext records, and count them in `recording_blob_ingestion_v2_ml_legacy_envelopes_dropped_total`.
Headerless queued messages mean v1.
Unknown versions are rejected, and so is an image reference whose version does not match the header.
The metadata sink resolves each row's session key from the row's own team and session identifiers before it seals the row for Parquet; a row whose key is deleted is dropped.

Legacy image references and paths remain available for v1 sessions.
Their HMAC key must remain stable while that data is in use.

## Configuration

New key manager and v2 storage settings use the `AI_RESEARCH_REPLAY_*` prefix:

- `KEY_TABLE`, `KMS_KEY_ARN`, and `AWS_REGION` select the key store and wrapping key.
- `KEY_CACHE_MAX`, `KEY_CACHE_LIFETIME_MS`, and `KMS_REQUESTS_PER_SECOND` bound the KMS plaintext cache and KMS traffic.
- `ROW_CACHE_MAX` and `ROW_CACHE_LIFETIME_MS` bound the stored key row cache. The lifetime applies to a session key row and is capped; a team image key row is held for up to 48 hours. A value that is not a positive integer stops the consumer at startup and names the setting.
- `IMAGE_FETCH_V2_DYNAMODB_TABLE` selects the fresh v2 frontier.
- `S3_PREFIX` selects v2 replay storage and defaults to `rrweb_2`.
- `S3_BUCKET` names the v3 bucket, which holds only AISR03 frames. A session that started at or after the v3 cutoff writes there, and v2 keeps its own bucket. The mirror, the sink and the image scrubber stop at startup when it is empty.
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

Use the real team ID to exclude all teams present in the model's training data before selecting eval examples.
The exclusion must cover every training month, not only the eval partition's month.
Use the encrypted reader for index entries, then fetch selected recording blocks to inspect their JSON-LD payloads.
Legacy v1 indexes retain their pseudonymized identifiers and daily partitions.

### Deletion worker isolation

The deletion task uses the `ai_research_privacy` Celery queue.
In prod-us, only the dedicated `ai-research-privacy-worker` deployment consumes this queue.
Its service account has a dedicated IAM role and cloud-database user.
The database user needs SELECT and UPDATE only on `posthog_aitrainingdeletionrequest`.
The worker starts with `bin/docker-worker-ai-training-privacy` and does not use shared Django signing secrets.
Its process-local signing key is not used for application requests.
The worker skips general migration checks; the outbox table must exist before deployment.
All processes that enqueue deletion work, including the general-purpose Temporal worker, need the key table setting.
Shared Django and Temporal workers cannot delete keys from the key table.
