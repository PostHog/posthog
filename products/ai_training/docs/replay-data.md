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
- The ML mirror drops a session if its ID is not UUIDv7 or its start year is beyond 9999.

Event timestamps, arrival times, retries, and flushes do not change the version.
Both versions can occur in one ingestion batch.
Their replay blocks, images, and metadata use separate storage paths.
The version applies to the whole session, including a session that crosses the cutoff.

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
ML outputs omit distinct IDs, including their hashes and pseudonyms.
The metadata consumer projects supported fields before storage, including for messages already in Kafka.
A session has one data key.
A team has one image key per session start month.
KMS wraps each data key with an encryption context that binds its owner and purpose.
Payload encryption uses XSalsa20-Poly1305.
The authenticated payload also binds the dataset kind and, for images, the object or reference being encrypted.
The envelope seals the raw payload with AES-256-GCM.
Its additional authenticated data is the JSON of `{"v": 3, "context": ...}` with sorted keys and no whitespace, so every reader rebuilds the same bytes.
The envelope is JSON with `v`, `context`, `nonce` (12 bytes, base64) and `ciphertext` (the sealed bytes followed by the 16-byte tag, base64).

Ingestion processes key state in batches:

1. Bulk-read session keys, team blocks, and image keys.
2. Resolve keys in memory while processing the batch.
3. Write each new key's month index entry, then the key with a conditional put.
4. Re-read the batch, adopt a competing writer's keys, drop sessions or teams blocked during the batch, then publish replay blocks or image messages.

A conditional put refuses to recreate a shredded session key.
A team blocked during a batch is dropped by the batch re-read and refused by every reader, and the deletion worker sweeps the team once more after the reader lease, so a key stored after the block is shredded.
Kafka offsets advance only after the required writes and publication succeed.
Bulk reads use batches of at most 100 keys; each new key is one conditional put, so no commit in the fleet waits on another.
Reads use strongly consistent `BatchGetItem` requests with bounded retries for unprocessed keys.

KMS plaintext caches reduce repeated decrypt calls.
A cache hit does not bypass live key and deletion checks.
Each process limits KMS concurrency and request rate; deployment capacity must account for the sum across replicas.
Readers check live state before each batch and permit key use for at most five minutes from the start of that read.
An expired read must obtain permission again.

The key table has no TTL or point-in-time recovery.
Its resource policy denies backups, exports, and enabling continuous backups or Kinesis copies.
Do not copy wrapped keys into object storage, logs, workflow payloads, or another persistent cache.
Restoring a deleted wrapped key would defeat deletion.

## Deletion

Existing recording, person, team, and organization deletion flows enqueue ML privacy work.
Person deletion resolves the combined supplied and profile distinct IDs through the replay ClickHouse index.
This lookup also runs when the user does not select replay deletion and includes IDs with no remaining person profile.
Only the resulting session IDs enter the ML privacy outbox.
A lookup failure stops the request before profile deletion so it can retry.
Team deletion and its privacy outbox request commit in the same database transaction.
If the outbox write fails, team deletion fails and can retry.
Consent changes do not enqueue privacy requests.
The outbox survives removal of the source team or organization.
Its team IDs refer to the original environment, without resolving a child environment to its parent.

| Scope   | Effect                                                                              |
| ------- | ----------------------------------------------------------------------------------- |
| Session | Remove its wrapped key and permanently block that session ID.                       |
| Person  | Resolve its session IDs through replay, then apply session deletion to each result. |
| Team    | Permanently block the team and remove its session and image keys.                   |

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
Existing read leases expire within five minutes.
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

V2 references are `image:v2:<team>:<month>:<hash>` and `imageurl:v2:<team>:<month>:<hash>`.
Images do not deduplicate across teams or session months.
Source messages use session keys; stored scrubbed images use team image keys.
Consumers reject malformed UUIDv7 session identifiers before reading DynamoDB.
Oversized identifiers cannot fail a whole bulk key lookup.
Inline images have an encrypted lookup for each reference, published after the shard and its index.
Readers fetch that lookup directly; a missing image does not require a scan of the team's image history.
Source deduplication includes the session, so deleting one source session cannot suppress another session's copy.
The v2 image-fetch frontier uses a separate, initially empty DynamoDB history table.
Its URL history expires eight days after the end of the session's UTC month.
Explicit HTTP freshness or cache restrictions can shorten this expiry; they cannot extend it.
Robots.txt and TDM reservation caches keep their shared origin keys and existing expiry rules.
It does not inherit v1 seen flags or successful fetch results.

ML Kafka producers write `ai_research_ingestion_version: 1` or `2`.
Retries and dead-letter replay preserve this header and the encrypted bytes.
Headerless queued messages mean v1.
Unknown versions and conflicting v2 ownership are rejected; a failed v2 decode never falls back to v1.

Legacy image references and paths remain available for v1 sessions.
Their HMAC key must remain stable while that data is in use.

## Configuration

New key manager and v2 storage settings use the `AI_RESEARCH_REPLAY_*` prefix:

- `KEY_TABLE`, `KMS_KEY_ARN`, and `AWS_REGION` select the key store and wrapping key.
- `KEY_CACHE_MAX`, `KEY_CACHE_LIFETIME_MS`, and `KMS_REQUESTS_PER_SECOND` bound ingestion key caching and KMS traffic.
- `IMAGE_FETCH_V2_DYNAMODB_TABLE` selects the fresh v2 frontier.
- `S3_PREFIX` selects v2 replay storage and defaults to `rrweb_2`.

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

### Privacy worker isolation

The privacy task uses the `ai_research_privacy` Celery queue.
In prod-us, only the dedicated `ai-research-privacy-worker` deployment consumes this queue.
Its service account has a dedicated IAM role and cloud-database user.
The database user needs SELECT and UPDATE only on `posthog_aitrainingdeletionrequest`.
The worker starts with `bin/docker-worker-ai-training-privacy` and does not use shared Django signing secrets.
Its process-local signing key is not used for application requests.
The worker skips general migration checks; the outbox table must exist before deployment.
All processes that enqueue privacy work, including the general-purpose Temporal worker, need the key table setting.
Shared Django and Temporal workers cannot delete keys from the key table.
