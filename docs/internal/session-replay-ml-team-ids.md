# ML mirror identifiers

AI Research owns the ML replay datasets.
The metadata and image consumers support versioned records with raw team IDs and legacy records with pseudonymous IDs.

## Block metadata

Block metadata with `format_version: 2` requires a positive decimal string in `team_id`.
The consumer preserves `session_id` and `distinct_id` as supplied by the producer.
It writes version 2 records to `<metadata-prefix>/v2/` and their replay indexes to `<metadata-prefix>-replay-index/v2/`.
Records without a format version use the legacy metadata prefix and replay index version 1.

Select a dataset version explicitly when reading S3.
A recursive scan of the metadata prefix can mix raw IDs and pseudonyms.

## Image references

Inline image references use `image:<teamId>:<hash>` with a raw team ID, or a 32-character hexadecimal team pseudonym for legacy data.
The native anonymizer preserves both formats when re-scrubbing trusted mirrored data.

| Format           | Shard prefix                | Index prefix               | Team column   |
| ---------------- | --------------------------- | -------------------------- | ------------- |
| Raw team ID      | `<image-prefix>/v2/shards/` | `<image-prefix>/v2/index/` | `team_id`     |
| Legacy pseudonym | `<image-prefix>/shards/`    | `<image-prefix>/index/`    | `pseudo_team` |

The image consumer separates the formats within mixed Kafka batches.
It commits offsets only after all shard and index writes succeed.

URL image references use `imageurl:<hash>` and share a global namespace under `<image-prefix>/url/`.
