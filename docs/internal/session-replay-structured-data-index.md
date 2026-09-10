# Session replay structured data index

The ML mirror writes a sparse Parquet index for full snapshots, `$json_ld` custom events, and URL changes.
Use it to find candidate labels and block locations without downloading DOM payloads.
The native anonymizer extracts metadata after scrubbing and passes it beside the serialized recording bytes.
The ordinary replay ingestion path does not extract this index.

## Storage and lookup

The existing metadata sink writes the index to the same bucket as block metadata.
Its prefix is `<block-metadata-prefix>-replay-index/v1/`.
For the default prefix, files have this form:

```text
block-metadata-replay-index/v1/kind=json_ld/session_start_date=2026-09-01/part-<writer>-<time>-<sequence>.parquet
block-metadata-replay-index/v1/kind=full_snapshot/session_start_date=2026-09-01/part-<writer>-<time>-<sequence>.parquet
block-metadata-replay-index/v1/kind=page/session_start_date=2026-09-01/part-<writer>-<time>-<sequence>.parquet
```

Each row identifies a pseudonymous team and session, the recording window, an event timestamp, and a zero-based event index within the decompressed block.
The block key and inclusive byte range locate the independently compressed block.
Timestamps use doubles so fractional milliseconds survive an exact join.
Window IDs match the IDs in the scrubbed recording lines.
The index contains no DOM nodes or JSON-LD payload text.

A `json_ld` row contains an optional `full_snapshot_ts_ms` reference and up to 64 distinct root types.
Types come from root objects, root arrays, and `@graph` members.
Nested entity properties, such as a product's offers, do not contribute types.
The types help select candidates; read the payload before deciding which label to use.

The index partitions each row by its session's UTC start date, decoded from UUIDv7 before pseudonymization.
Entries for one session stay under one date, including separate blocks and late arrivals across midnight.
This partition helps session lookups and cross-block joins. An arrival-date partition would make ingestion-time scans simpler, but would spread one session across dates.
The index omits non-v7 session IDs and starts outside the interval from seven days before the block's last event through that event.
Normal replay storage and block metadata continue for those sessions.
For an event-time search, include the preceding seven session-start dates and filter `event_ts_ms`.

## Pairing labels with snapshots

Read the requested session-start partitions into DuckDB views named `labels`, `snapshots`, and `pages`.
Use `union_by_name=true` when reading Parquet files across schema versions.
A label with a reference can join a snapshot in another payload or block:

```sql
SELECT DISTINCT
    j.team_id, j.session_id, j.window_id, j.full_snapshot_ts_ms,
    j.root_types,
    j.block_s3_key AS label_block, j.block_byte_start AS label_start,
    j.block_byte_end AS label_end, j.event_index AS label_event_index,
    s.block_s3_key AS snapshot_block, s.block_byte_start AS snapshot_start,
    s.block_byte_end AS snapshot_end, s.event_index AS snapshot_event_index
FROM labels j
JOIN snapshots s
  ON j.team_id = s.team_id
 AND j.session_id = s.session_id
 AND j.window_id = s.window_id
 AND j.full_snapshot_ts_ms = s.event_ts_ms
WHERE NOT j.block_index_truncated AND NOT s.block_index_truncated;
```

This query returns candidates. A timestamp is not a unique rrweb event ID.
Fetch the referenced blocks, check the event kind and timestamp at each index, and deduplicate identical snapshots by content.
Reject a join if distinct full snapshots still share its team, session, window, and timestamp.
Several JSON-LD scripts can label one snapshot. Combine their labels only after that validation.
Do not count them as separate training examples.

Older SDK events and mutation captures have no explicit snapshot reference.
They still appear in the label index, but proximity matching is approximate and must stay separate from explicitly linked pairs.
Out-of-order arrivals need no ingestion-side session cache: a later query can join both entries once both blocks exist.

## Domain and page coverage

Use the latest preceding `page` event in the same team, session, and window as provisional URL context.
Page entries are independent rows because a URL change and a snapshot can arrive in separate payloads.
Check that context when fetching the recording; missing navigation events or truncated index blocks can leave it incomplete.

URLs come from the anonymizer's post-scrub metadata.
Their hostnames permit site grouping, but redacted paths can merge distinct pages.
Report unique scrubbed URLs as a lower bound on page diversity.
Exact page counts need a separately reviewed fingerprint of the original page identity.
For domain-disjoint datasets, normalize hostnames to registrable domains with a public suffix list before assigning train, dev, and test groups.

## Delivery and limits

Each block has a 128 KiB index budget. If it exceeds that budget, its retained entries have `block_index_truncated=true`.
The recorder still stores all replay events.
The metadata batcher also flushes at 32 MiB of input messages, checked after each Kafka batch.
This limits accumulation to that threshold plus one input batch; decoded objects and Parquet encoding require additional memory.
The metadata sink writes index partitions sequentially and commits Kafka offsets only after all index and block-metadata writes succeed.
A partial upload followed by a retry can produce duplicate rows.
Deduplicate rows by team, session, block key, byte range, event index, and kind before counting them.
Repeated source blocks can also have different storage keys, so dataset preparation still needs content deduplication.

The existing write-error metric includes index failures.
`ml_mirror_replay_index_rows_written_total` counts uploaded entries by kind, including retries.
`ml_mirror_replay_index_skipped_total` counts invalid entries, blocks without a usable session start, and truncated blocks.
These counters measure indexing, not unique sessions or pages.

The consumer can deploy before the producer because index metadata is optional.
Deploy the consumer first: an older consumer accepts new metadata but does not write the index.
Confirm that the sink's S3 permissions and bucket lifecycle policy cover the new sibling prefix before rollout.
This change does not backfill old recordings.
