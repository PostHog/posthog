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

A `json_ld` row contains an optional `url` and up to 64 distinct root types.
The schema also accepts `full_snapshot_ts_ms`, but the URL-only SDK change does not send this optional reference.
Types come from root objects, root arrays, and `@graph` members.
Nested entity properties, such as a product's offers, do not contribute types.
The types help select candidates; read the payload before deciding which label to use.

The index partitions each row by its session's UTC start date, decoded from UUIDv7 before pseudonymization.
Entries for one session stay under one date, including separate blocks and late arrivals across midnight.
This partition helps session lookups and cross-block joins. An arrival-date partition would make ingestion-time scans simpler, but would spread one session across dates.
The index omits non-v7 session IDs and starts outside the interval from seven days before the block's last event through that event.
Normal replay storage and block metadata continue for those sessions.
For an event-time search, include the preceding seven session-start dates and filter `event_ts_ms`.

## Full snapshot URLs

A `full_snapshot` row receives the scrubbed URL from the preceding Meta event in the same recording window.
The recorder requires consecutive events within that window and nondecreasing timestamps.
Other windows and payload boundaries within a block do not break this association.
The URL enriches the index row; it does not change the stored rrweb event.

The recorder keeps this pending Meta only within its current block.
A block boundary, an intervening event, or reversed arrival order can leave the snapshot row without a URL.
Older anonymizer metadata also lacks the Meta flag required for this association.
Readers can use the durable `page` rows to find candidates across blocks, without an ingestion-side session cache.
A Meta event without a usable URL still creates a `page` row, which stops readers from carrying an earlier URL forward.
Do not filter out these rows before a temporal join.

## Pairing labels with snapshots

Read the requested session-start partitions into DuckDB views named `labels`, `snapshots`, and `pages`.
Use `union_by_name=true` when reading Parquet files across schema versions.
The following query finds candidates by URL and time, including separate blocks and out-of-order arrivals.
Its one-second Meta gap and two-second label gap are example selection parameters, not SDK guarantees.
Measure match coverage and audit payloads before choosing the final thresholds.

```sql
WITH page_urls AS (
    SELECT team_id, session_id, window_id, event_ts_ms,
           CASE WHEN count(url) = count(*) AND count(DISTINCT url) = 1
                THEN min(url) END AS url
    FROM pages
    GROUP BY team_id, session_id, window_id, event_ts_ms
), snapshot_urls AS (
    SELECT s.* EXCLUDE (url),
           coalesce(s.url, CASE WHEN s.event_ts_ms - p.event_ts_ms <= 1000
                               THEN p.url END) AS url
    FROM (SELECT DISTINCT * FROM snapshots) s
    ASOF LEFT JOIN page_urls p
      ON s.team_id = p.team_id
     AND s.session_id = p.session_id
     AND s.window_id = p.window_id
     AND s.event_ts_ms >= p.event_ts_ms
), incomplete_sessions AS (
    SELECT team_id, session_id FROM labels WHERE block_index_truncated
    UNION
    SELECT team_id, session_id FROM snapshots WHERE block_index_truncated
    UNION
    SELECT team_id, session_id FROM pages WHERE block_index_truncated
)
SELECT DISTINCT
    j.team_id, j.session_id, j.window_id, j.url, j.root_types,
    j.event_ts_ms AS label_ts_ms, s.event_ts_ms AS snapshot_ts_ms,
    j.block_s3_key AS label_block, j.block_byte_start AS label_start,
    j.block_byte_end AS label_end, j.event_index AS label_event_index,
    s.block_s3_key AS snapshot_block, s.block_byte_start AS snapshot_start,
    s.block_byte_end AS snapshot_end, s.event_index AS snapshot_event_index
FROM labels j
JOIN snapshot_urls s
  ON j.team_id = s.team_id
 AND j.session_id = s.session_id
 AND j.window_id = s.window_id
 AND j.url = s.url
 AND abs(j.event_ts_ms - s.event_ts_ms) <= 2000
WHERE j.url IS NOT NULL AND j.url <> ''
  AND NOT EXISTS (
      SELECT 1 FROM incomplete_sessions i
      WHERE i.team_id = j.team_id AND i.session_id = j.session_id
  )
  AND NOT EXISTS (
      SELECT 1 FROM page_urls p
      WHERE p.team_id = j.team_id AND p.session_id = j.session_id
        AND p.window_id = j.window_id
        AND p.event_ts_ms BETWEEN least(j.event_ts_ms, s.event_ts_ms)
                              AND greatest(j.event_ts_ms, s.event_ts_ms)
        AND p.url IS DISTINCT FROM j.url
  );
```

This query returns candidates, not verified pairs.
A matching scrubbed URL and timestamp gap cannot prove that a JSON-LD mutation describes an earlier DOM snapshot.
The index cannot prove adjacency across blocks because it omits most event kinds.
Missing events, masked Meta events, and URL collisions can also conceal a navigation.
Do not treat a fallback URL as equivalent to an observed Meta-to-snapshot association.
A later query can find late arrivals once both blocks exist; record the input object list to make a dataset run reproducible.

Fetch each distinct block key and inclusive byte range once, then decompress its Snappy JSONL recording lines.
Check the window, event kind, and timestamp at each event index before using its payload.
Reject ambiguous matches, including distinct full snapshots that share a timestamp or several plausible snapshots for one label.
A timestamp is not a unique rrweb event ID.
Deduplicate repeated snapshots by content before resolving such ambiguity.
Several JSON-LD scripts can label one snapshot; combine their labels after validation instead of counting separate examples.
Define a label policy for multiple root types and `@graph` entities before training a single-root classifier.

The query excludes sessions with visible truncated index rows, but cannot detect a missing block or an entirely absent index.
For strict examples, inspect the surrounding replay events and reject pairs whose page state cannot be established.
Exclude JSON-LD rows without URLs; do not infer those URLs from older SDK navigation events.

## Domain and page coverage

Use the `url` on each `json_ld` row for site and page coverage.
The SDK captures it in `data.href` at the same time as the label, after applying replay URL masking and hash settings.
The anonymizer scrubs it again before extracting index metadata.
This works when navigation events and JSON-LD arrive in separate payloads and needs no session URL cache.

Exclude rows without a usable URL from coverage counts and dataset selection.
Older SDKs do not send this field; URL masking can also omit it.
The index retains those rows, but coverage queries do not infer their URLs from `page` events.
JSON-LD events with a URL do not also create a `page` index row.

Count distinct normalized scrubbed URLs as page families.
Scrubbing can group similar paths, which helps deduplicate similar pages.
These counts do not measure distinct DOM structures.
For domain-disjoint datasets, normalize hostnames to registrable domains with a pinned public suffix list, including its private suffix rules.
Store a deterministic domain-to-split assignment before sampling examples.
Never split individual sessions at random, because sessions from the same site would leak across splits.

The index supplies candidate types, URLs, timestamps, and fetch locations; it does not supply DOM hashes or verified training labels.
A dataset builder still needs to:

1. Deduplicate index retries, validate candidate pairs, and consolidate their labels.
2. Normalize scrubbed URLs and select a representative per page family, with a per-domain cap.
3. Deduplicate DOM content globally so copies under different domains cannot leak across splits.
4. Balance sampling within the fixed domain splits, then save the selection parameters and source locations in a manifest.
5. Report usable examples, sessions, unique page families, domains, and root-type counts for each split, plus rejected and ambiguous candidates.

Keep split assignment stable across resampling and dataset versions.
Audit examples where one scrubbed URL has different labels; URL deduplication alone must not silently choose a conflicting label.
Exclude cross-split content duplicates or keep their domain groups together before freezing the final split.

This layout supports a bounded-date Parquet scan followed by selective block fetches.
It does not provide an S3 point lookup by domain or URL: those filters still scan the selected date partitions.
Cache the selected index locally for repeated sampling and split experiments.
A compacted metadata table can reduce file-listing overhead later without changing SDK capture or replay storage.

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

## JSON-LD URL rollout

Deploy the anonymizer and mirror changes that scrub and index `data.href` before releasing the SDK change that sends it.
The existing index schema already accepts the optional URL column, so this addition needs no metadata-consumer rollout.
Existing events without `data.href` remain readable and do not contribute to URL-based coverage.
