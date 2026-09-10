# ML mirror identifiers

AI Research owns the ML replay datasets.
The mirror stores scrubbed recordings from teams that opt in to training.
It preserves raw identifiers in metadata so data preparation can join recordings to analytics events and surfacing scores.

## Identifiers and joins

| Field         | Stored value                | Present in                                                         |
| ------------- | --------------------------- | ------------------------------------------------------------------ |
| `team_id`     | Team ID as a decimal string | Block metadata, replay index, inline image index, surfacing scores |
| `session_id`  | Original session ID         | Block metadata, replay index, surfacing scores                     |
| `distinct_id` | Original distinct ID        | Block metadata                                                     |

Join session data on both `team_id` and `session_id`.
Include `team_id` when joining analytics events by `distinct_id`.
The score exporter includes sessions outside the training opt-in set, so data preparation must join scores to opted-in mirror sessions.

Identifiers belong in data preparation metadata and must be removed from model inputs.
Resolve inline image references to image content before training because the references contain team IDs.

## Storage paths

| Dataset             | Default prefix                    |
| ------------------- | --------------------------------- |
| Replay blocks       | `rrweb_2/`                        |
| Block metadata      | `block-metadata/v2/`              |
| Replay index        | `block-metadata-replay-index/v2/` |
| Inline image shards | `scrubbed-images/v2/shards/`      |
| Inline image index  | `scrubbed-images/v2/index/`       |
| URL images          | `scrubbed-images/url/`            |
| Surfacing scores    | `score/v2/`                       |

`SESSION_RECORDING_ML_S3_PREFIX` sets the replay block prefix and defaults to `rrweb_2`.
`SESSION_RECORDING_V2_S3_PREFIX` configures ordinary replay storage independently.
Metadata, image, and score paths use their configured prefixes with the version suffixes shown above.
Select a dataset version explicitly: a recursive scan of a parent prefix can mix raw IDs and legacy pseudonyms.

See the [structured data index guide](session-replay-structured-data-index.md) for replay index partitions and block lookup.

## Image references

Inline image references use `image:<teamId>:<hash>`.
The image index contains the raw `team_id` and `format_version = 2`.
Image content hashes use a key derived for each team.

URL image references use `imageurl:<hash>` in a global namespace.
Their objects use `scrubbed-images/url/`.
Keep the image hash key stable so references and cache lookups continue to resolve.

## Legacy records

Block metadata with `format_version: 2` contains raw identifiers.
Records without a format version contain pseudonyms and use `block-metadata/` and `block-metadata-replay-index/v1/`.
The consumer writes the formats separately, including when they arrive in the same Kafka batch.
Legacy records cannot join directly to raw identifiers.

Legacy inline image references contain a 32-character hexadecimal team pseudonym.
Their shards and index use `scrubbed-images/shards/` and `scrubbed-images/index/`.
Legacy index rows contain `pseudo_team` and `format_version = 1`.
The image consumer accepts both formats and commits Kafka offsets only after all shard and index writes succeed.

Read replay blocks from the locations in their metadata; legacy block locations remain valid.
Legacy score exports remain under `score/` and cannot join directly to raw identifiers.
