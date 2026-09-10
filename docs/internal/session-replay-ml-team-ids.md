# ML mirror team ID compatibility

The Parquet sink and image consumers accept raw team IDs as well as legacy team pseudonyms.
The mirror and score exporter still produce team pseudonyms.
This compatibility step does not change the active dataset.

## Consumer formats

Block metadata with `format_version: 2` must carry a positive decimal team ID string.
The sink writes these records to `block-metadata/v2/` and their replay indexes to `block-metadata-replay-index/v2/`.
Records without a version retain their legacy paths.

Inline image references can contain a raw team ID or a legacy 32-character hexadecimal pseudonym.
Raw-team images use `scrubbed-images/v2/shards/` and `scrubbed-images/v2/index/`, with `team_id` in the index.
Legacy images retain their existing paths and `pseudo_team` column.
Mixed batches write separate shards and indexes before committing Kafka offsets.
Global URL image references and paths stay unchanged.
The native anonymizer preserves both formats when re-scrubbing trusted mirrored data.

## PR merge order

Each step is a separate PR.
Wait for each deployment or infrastructure apply to complete before merging the next PR.
AI Research owns this rollout.

1. Add S3 permissions for the new dataset paths.
2. Add consumer compatibility and verify the Parquet sink and image-scrub consumer deployment.
3. Add the new ML replay prefix to the charts configuration. Producers at this stage ignore this setting.
4. Switch the mirror and score exporter to raw team IDs and versioned paths.
5. Switch Athena to the versioned datasets after verifying new data and preparing downstream readers.

Keep compatible consumers during any producer rollback, including while dead-letter replays drain.
