# ML replay data

AI Research owns the ML mirror, its encryption keys, and its training readers.
The mirror collects scrubbed recordings from organizations that consent to AI training.
Its storage and deletion implementation is separate from production session replay.

## Session versions

The cutoff is **Monday, 2026-09-14 at 11:00 UTC**, which is noon in Europe/London.
The session UUIDv7 timestamp selects the version:

- Before the cutoff: v1 uses HMAC team, session, and distinct IDs.
- At or after the cutoff: v2 uses raw IDs and encrypted payloads.
- An invalid UUIDv7 timestamp selects v1.

Event timestamps, arrival times, retries, and flushes do not change the version.
Both versions can occur in one ingestion batch.
Their replay blocks, images, and metadata use separate storage paths.
The version applies to the whole session, including a session that crosses the cutoff.

## Consent periods

An organization has one current consent state: allowed, grant timestamp, change timestamp, and revision.
Django records a consent change and its delivery request in the same transaction as the organization change.
A background worker publishes that state to DynamoDB.
Conditional revision checks prevent delayed requests from replacing newer state.

A v2 session is eligible only when consent is allowed and its start timestamp is at or after the current grant timestamp.
Withdrawing consent removes existing session and image keys.
Granting consent again permits new sessions with fresh keys.
Sessions from an earlier consent period remain excluded, including delayed Kafka messages and retries.
A delayed withdrawal only removes keys from the withdrawn period or earlier periods.

Run `python manage.py initialize_ai_training_consent` to initialize existing organizations after enabling the privacy table.
The command preserves consent state that a concurrent application change has already created.
The privacy worker must publish the initial state before v2 collection starts.
Missing consent state blocks v2 collection.

## Keys and batch processing

The independent DynamoDB table stores session keys, team image keys, consent state, deletion markers, and distinct-ID associations.
A session has one data key.
A team has one image key per consent period.
KMS wraps each data key with an encryption context that binds its owner, purpose, and consent timestamp.
Payload encryption uses XSalsa20-Poly1305.
The authenticated payload also binds the dataset kind and, for images, the object or reference being encrypted.

Ingestion processes privacy state in batches:

1. Bulk-read session keys, consent, team blocks, distinct-ID blocks, and image keys.
2. Resolve keys and accumulate associations in memory while processing the batch.
3. Commit bounded DynamoDB transactions before publishing replay blocks or image messages.
4. On a competing write, bulk-read the winning state and retry with its keys.

Conditional writes prevent a deletion or consent change from being undone by an in-flight batch.
Kafka offsets advance only after the required writes and publication succeed.
DynamoDB transactions have at most 100 actions and stay below the request size limit.
Reads use strongly consistent `BatchGetItem` requests with bounded retries for unprocessed keys.

KMS plaintext caches reduce repeated decrypt calls.
A cache hit does not bypass the DynamoDB key and consent checks.
Each process limits KMS concurrency and request rate; deployment capacity must account for the sum across replicas.
Readers check live state before each batch and permit key use for at most five minutes from the start of that read.
An expired read must obtain permission again.

The privacy table has no TTL or point-in-time recovery.
Its resource policy denies backups, exports, and enabling continuous backups or Kinesis copies.
Do not copy wrapped keys into object storage, logs, workflow payloads, or another persistent cache.
Restoring a deleted wrapped key would defeat deletion.

## Deletion

Existing recording, person, team, and organization deletion flows enqueue ML privacy work.
Person deletion includes distinct IDs even when the user does not select the replay deletion option.
An organization changing AI training consent to false also enqueues key removal.
The outbox survives removal of the source team or organization.
Its team IDs refer to the original environment, without resolving a child environment to its parent.

| Scope              | Effect                                                                                          |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| Session            | Remove its wrapped key and permanently block that session ID.                                   |
| Distinct ID        | Permanently block the team and distinct-ID pair, then remove keys for every associated session. |
| Team               | Permanently block the team and remove its session and image keys.                               |
| Consent withdrawal | Remove session and image keys from the withdrawn consent period and all earlier periods.        |

Distinct IDs and sessions have a many-to-many relationship.
Ingestion records both directions of each association before publishing data.
Team and distinct-ID lookups use 32 session shards with strongly consistent queries; they do not require ClickHouse or an eventually consistent secondary index.
Deleting one distinct ID deletes each complete associated session, including events with other distinct IDs.
A later event for a blocked distinct ID also blocks its session.

Deletion uses resumable query pages and stores progress in the outbox.
A failed request backs off without blocking unrelated requests.
Completion follows key removal and the five-minute reader lifetime.
Scrubbed images remain available after session or distinct-ID deletion, but become unreadable after team deletion or consent withdrawal.

This mechanism covers encrypted v2 objects.
It does not erase legacy plaintext objects, previously downloaded data, derived training artifacts, or a trained model.
Legacy dataset retirement needs a separate storage operation before claiming deletion across the entire bucket.

## Data layout and readers

| Dataset                   | Default path                                                | Encryption key                          |
| ------------------------- | ----------------------------------------------------------- | --------------------------------------- |
| Replay blocks             | `rrweb_2/`                                                  | Session                                 |
| Metadata catalog          | `block-metadata/v2/dt=<arrival-date>/`                      | Each row's payload uses its session key |
| Inline image shards       | `scrubbed-images/v2/<team>/<grant>/shards/`                 | Team and consent period                 |
| Inline image lookups      | `scrubbed-images/v2/<team>/<grant>/lookup/<hash>.encrypted` | Team and consent period                 |
| Inline image indexes      | `scrubbed-images/v2/<team>/<grant>/index/`                  | Team and consent period                 |
| URL images                | `scrubbed-images/v2/<team>/<grant>/url/<hash>`              | Team and consent period                 |
| Score pages               | `score/v2/dt=<session-date>/`                               | Each row's payload uses its session key |
| Completed score manifests | `score/v2-manifests/dt=<session-date>/`                     | No payload data or keys                 |

Metadata catalogs expose raw `team_id`, `session_id`, `consent_granted_at`, `format_version`, and an encrypted `payload`.
Distinct IDs, URLs, block locations, and replay indexes are inside that payload.
V2 does not write a separate plaintext replay index.
Score catalogs expose team and session IDs, the consent timestamp, and an encrypted score payload.
Only sessions with live, eligible ML keys receive encrypted score rows.

Athena can select catalog rows but cannot decrypt replay fields or scores.
Training readers must bulk-read live keys and consent before decrypting.
If a download exceeds the key read lifetime, readers must check live eligibility again before decryption.
Cross-account readers use the full DynamoDB table ARN and the prod-us KMS key ARN.
Both accounts must authorize the reader role.
Readers have key-read and decrypt permissions; they cannot create keys or change deletion state.

Use metadata block locations and byte ranges to fetch recordings, then decrypt before decompressing.
Include all relevant metadata arrival dates when collecting a session with late blocks.
Score export writes bounded pages and publishes a manifest only after the last page succeeds.
Use the newest completed manifest for each date and hash partition; a recursive score scan can include partial or superseded exports.

Join analytics on both raw team and session IDs, or on team and distinct IDs.
Remove identifiers from model inputs.
Resolve image references before training because they contain team IDs.

## Images and Kafka

V2 references are `image:v2:<team>:<grant>:<hash>` and `imageurl:v2:<team>:<grant>:<hash>`.
Images do not deduplicate across teams or consent periods.
Source messages use session keys; stored scrubbed images use team image keys.
Inline images have an encrypted lookup for each reference, published after the shard and its index.
Readers fetch that lookup directly; a missing image does not require a scan of the team's image history.
Source deduplication includes the session, so deleting one source session cannot suppress another session's copy.
The v2 image-fetch frontier uses a separate, initially empty DynamoDB history table.
It does not inherit v1 seen flags or successful fetch results.

ML Kafka producers write `ai_research_ingestion_version: 1` or `2`.
V2 messages also carry `ai_research_consent_granted_at`, which must match the authenticated envelope.
Retries and dead-letter replay preserve these headers and the encrypted bytes.
Headerless queued messages mean v1.
Unknown versions and conflicting v2 ownership are rejected; a failed v2 decode never falls back to v1.

Legacy image references and paths remain available for v1 sessions.
Their HMAC key must remain stable while that data is in use.

## Configuration

New privacy settings use `AI_RESEARCH_REPLAY_*`:

- `PRIVACY_TABLE`, `KMS_KEY_ARN`, and `AWS_REGION` select the key store and wrapping key.
- `KEY_CACHE_MAX`, `KEY_CACHE_LIFETIME_MS`, and `KMS_REQUESTS_PER_SECOND` bound ingestion key caching and KMS traffic.
- `IMAGE_FETCH_V2_DYNAMODB_TABLE` selects the fresh v2 frontier.
- `S3_PREFIX` selects v2 replay storage and defaults to `rrweb_2`.
- `SCORE_EXPORT_*` settings select the score export destination.

Established HMAC and score settings retain their transition aliases.
When both aliases are set, the `AI_RESEARCH_REPLAY_*` value takes precedence, including an explicit empty value.
The wrapped HMAC secret keeps the single name `SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY` in both the environment and secret store.
It has no new alias.
Renaming configuration must not rotate that key.
