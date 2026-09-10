# ML mirror team IDs

The ML mirror preserves raw team IDs so data preparation can join replay metadata to analytics events.
Session IDs and distinct IDs remain HMAC pseudonyms.
The event scrubber, training opt-in gate, and image content HMACs keep their existing behavior.
Keep identifiers in data preparation metadata and remove them from model inputs.
This also applies to the team ID inside inline image references: resolve those references to image content before training.

## Storage

New producers emit block metadata with `format_version: 2` and a decimal string in `team_id`.
The string type matches the existing Parquet schemas.
The metadata consumer accepts queued records without a version as legacy records and writes them separately.
It never interprets a legacy pseudonym as a raw team ID.

| Dataset             | New data                          | Queued legacy data                            |
| ------------------- | --------------------------------- | --------------------------------------------- |
| Replay blocks       | `rrweb_2/`                        | Existing block locations stay valid           |
| Block metadata      | `block-metadata/v2/dt=.../`       | `block-metadata/dt=.../`                      |
| Replay index        | `block-metadata-replay-index/v2/` | `block-metadata-replay-index/v1/`             |
| Inline image shards | `scrubbed-images/v2/shards/`      | `scrubbed-images/shards/`                     |
| Inline image index  | `scrubbed-images/v2/index/`       | `scrubbed-images/index/`                      |
| Surfacing scores    | `score/v2/dt=.../`                | Existing `score/dt=.../` files stay unchanged |

`SESSION_RECORDING_ML_S3_PREFIX` sets the replay block prefix and defaults to `rrweb_2`.
It is independent of `SESSION_RECORDING_V2_S3_PREFIX`, which configures ordinary replay storage.
The other paths use the configured metadata, image, and score prefixes with the version suffixes shown above.
Readers must select the versioned paths explicitly; a recursive scan of the parent prefix can mix both datasets.
There is no backfill of legacy team pseudonyms.

New inline image references use `image:<teamId>:<hash>`.
The consumer accepts both decimal team IDs and legacy 32-character hexadecimal pseudonyms.
New image index rows use `format_version = 2` and a `team_id` column.
Legacy rows use `format_version = 1` and `pseudo_team`.
If an internal image record contains both fields, `teamId` takes precedence.
Mixed batches write separate shards and indexes before committing Kafka offsets.

URL image references remain global: `imageurl:<hash>`.
Their objects stay under `scrubbed-images/url/` so crawl-history deduplication and existing references remain valid.

Score exports preserve raw team IDs and keep the existing session pseudonym construction.
The exporter includes scored sessions outside the training opt-in set.
Data preparation must join scores to opted-in mirror sessions before building training data.
Joining analytics events by session also requires the existing session pseudonym transformation.

## Rollout

1. Apply the S3 identity policies and bucket policy for `rrweb_2/` and the replay index paths.
   Keep legacy paths accessible while old deployments and queued records drain.
2. Deploy the Parquet sink and image scrub consumers before the mirror producers.
   Older image consumers reject references containing decimal team IDs.
3. Deploy the mirror, including its rebuilt native anonymizer, and the score exporter.
4. Point Athena and data preparation readers at the versioned datasets.
   Update inline image lookup code to use `team_id` and the versioned index path.
5. Check new block locations, metadata team IDs, image index joins, and Kafka offset progress.

Rolling back a producer resumes legacy writes without changing existing versioned data.
Keep consumers that accept both formats until all new-format records have drained, including dead-letter replays.
