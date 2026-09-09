# ClickHouse utility UDFs

`JSONCleanPostHogEventProperties` groups `$feature/<key>` event properties into `$feature_flags`.
Before emitting JSON for insertion, it sorts the keys in `$feature_flags` alphabetically using case-sensitive string order.
This also applies to existing `$feature_flags` objects, after cleanup resolves duplicates and expands dotted keys.
Flag values and person-property ordering follow the existing cleanup rules.

See [the utility UDF README](../../clickhouse-udfs/util/README.md) for build and integration-test commands.

The event, person, and temporary cleaners reuse at most 4,096 parser nodes across rows.
Recycled nodes keep small backing arrays for reuse and release larger arrays whose capacity exceeds twice their used length, so a wide row does not make later small rows repeatedly clear oversized arrays.
They clear references across the remaining backing arrays, including entries removed during cleanup, so borrowed property keys do not retain previously processed input rows.
The parser validates discarded properties without allocating their value trees or decoding their strings into buffers.
Dotted-key expansion reuses a scratch entry slice and up to eight cleared backing arrays, one per size class, totaling less than 192 KiB.
The backing-array cache releases buffers larger than the next input row; scratch slices and lookup maps exceeding 4,096 entries are released.
Output and decoded-string buffers larger than 64 KiB are released when their capacity exceeds twice the next input row's length.
Each worker uses 64 KiB input and output buffers and borrows ordinary input rows directly from the reader.
Rows exceeding the reader buffer are assembled into an owned slice without imposing a new row-size limit.
These limits bound reuse, not the size of an accepted property: a large retained document still needs memory proportional to its contents.

### Array nesting limit

The event, person, and temporary cleaners accept at most eight nested arrays along any path, including arrays separated by objects.
This limit is separate from the general JSON depth limit of 300.
Small documents with deeply nested arrays and nulls can cause excessive memory allocation during ClickHouse JSON type inference.
The eight-array limit is a conservative input policy, not a guarantee against every possible inference failure.

The parser counts array nesting even inside discarded properties and checks the normalized result before emitting it.
The second check covers arrays decoded from strings or introduced by schema normalization.
Event and person cleaners preserve a rejected document verbatim as an escaped JSON string under `$unparseable_properties`.
The rejected document's original properties are no longer available as individually queryable JSON paths.
The temporary cleaner emits `{}` because the permanent cleaner preserves the original input, including temporary properties.
Run both event cleaners on the original document to retain that guarantee.
Malformed JSON still fails instead of entering this quarantine path.

### `JSONCleanPostHogTemporaryProperties(json)`

Accepts a JSON object and retains only the following top-level properties, including their dotted descendants. It uses the event cleaner's dotted-key expansion, null-object-field removal, duplicate handling, and integer protection, without coercing values to declared schema types. Non-object input fails.

| Category                      | Allowlist                                                                                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Person and group instructions | `$set`, `$set_once`, `$unset`, `$group_set`                                                                                                      |
| SDK diagnostics               | Every `$sdk_debug_*` property, including session duration                                                                                        |
| Flag diagnostics              | `$feature_flag_request_id`                                                                                                                       |
| Replay diagnostics            | `$debug_first_full_snapshot_timestamp`, `$snapshot_max_depth_exceeded`, `$sess_rec_flush_size`                                                   |
| Replay configuration          | `$session_recording_remote_config`, `$session_recording_network_payload_capture`, `$session_recording_canvas_recording`, `$replay_script_config` |
| Transport diagnostics         | `$sent_at`, `$lib_rate_limit_remaining_tokens`, `$lib_custom_api_host`                                                                           |

`$feature_flag_request_id` moves to temporary properties on every event type. `$debug_images` remains in permanent properties. Feature-flag payloads and `$active_feature_flags` are excluded from both outputs. Matching applies only at the root: a custom object's nested `$set` is not a temporary property.

Run both cleaners on the original JSON; the event cleaner has already discarded the temporary properties. Apply person/group instructions before splitting stored event properties. Retention belongs to the destination column's TTL and insertion time; this function does not expire data itself.

```sql
WITH '{"$set":{"score":7},"$sdk_debug_probe":true,"$sdk_debug_current_session_duration":42,"$feature_flag_request_id":"request-example","custom":"kept"}' AS raw_properties
SELECT
    JSONCleanPostHogEventProperties(raw_properties) AS properties,
    JSONCleanPostHogTemporaryProperties(raw_properties) AS temporary_properties;
-- properties: {"custom":"kept"}
-- temporary_properties: {"$set":{"score":7},"$sdk_debug_probe":true,"$sdk_debug_current_session_duration":42,"$feature_flag_request_id":"request-example"}
```

Both functions use the same executable. The temporary entry point uses `--temporary-properties` with the existing chunk protocol.

Documents exceeding the shared depth limit produce `{}` in the temporary output; the permanent cleaner quarantines the original document.

### Benchmarking the cleaner

`BenchmarkProcessFixture` measures cleaning with a reused processor and output buffer.
One fixture operation processes the entire supplied file, so divide allocations and elapsed time by its row count for per-row figures.

To use the public [JSONBench Bluesky dataset](https://github.com/ClickHouse/JSONBench), run these commands from `clickhouse-udfs/util`:

```sh
mkdir -p /tmp/cleaner-bench
curl -fL https://clickhouse-public-datasets.s3.amazonaws.com/bluesky/file_0001.json.gz -o /tmp/cleaner-bench/bluesky.json.gz
gzip -dk /tmp/cleaner-bench/bluesky.json.gz
head -n 10000 /tmp/cleaner-bench/bluesky.json > /tmp/cleaner-bench/sample.json
BENCH_FILE=/tmp/cleaner-bench/sample.json go test -run '^$' -bench Fixture -benchmem -cpu=1 -count=5 ./cmd/json_clean_posthog_event_properties_udf
go test -run '^$' -bench Process -benchmem -cpu=1 -count=5 ./cmd/json_clean_posthog_event_properties_udf
```

For whole-file throughput and process memory, build the executable and process the decompressed file directly.
Keep decompression outside the timed command and compare output hashes before interpreting timings.
On macOS, `/usr/bin/time -l` reports peak RSS in bytes; on Linux, `/usr/bin/time -v` reports it in KiB.

```sh
go build -o /tmp/cleaner-bench/cleaner ./cmd/json_clean_posthog_event_properties_udf
GOMAXPROCS=1 /usr/bin/time -l /tmp/cleaner-bench/cleaner < /tmp/cleaner-bench/bluesky.json > /dev/null
```

#### Results recorded September 8, 2026

Baseline: commit `8044a57049952b3423b5e26a8d85ddb1bb8e6953`.
Host: Apple M4 Pro, macOS arm64, Go 1.25.5.
The Bluesky file contains 1,000,000 rows and 480,778,277 bytes, including newlines.
Its decompressed SHA-256 is `7beb29f6c036fe784754ff34d68d1f216c6cc89de12155da06f725bdf5c8536e`.
Native executable results are medians of seven runs with `GOMAXPROCS=1`, alternating baseline, first-pass, and final binaries, with cached file input and output sent to `/dev/null`.
RSS is the median of each run's maximum resident set size, not live heap size.

| Workload                                   |  Before | First pass |   Final | Speedup | Peak RSS before / final |
| ------------------------------------------ | ------: | ---------: | ------: | ------: | ----------------------: |
| Bluesky, event executable                  |  2.04 s |     0.86 s |  0.57 s |   3.58× |        24.50 / 8.62 MiB |
| Bluesky, person executable                 |  1.87 s |     0.77 s |  0.52 s |   3.60× |        23.48 / 8.62 MiB |
| Bluesky, temporary executable              |  1.34 s |     0.52 s |  0.32 s |   4.19× |        23.83 / 3.72 MiB |
| Large discarded payloads, event executable |  0.58 s |     0.30 s |  0.15 s |   3.87× |        30.36 / 8.55 MiB |
| Bluesky, event UDF inside ClickHouse       | 2.080 s |    0.952 s | 0.710 s |   2.93× |            Not measured |

The discarded-payload file repeats the synthetic `BenchmarkProcessWorkloads/dropped` row 1,000 times, totaling 172,018,000 bytes.
Its repeated shape exercises disposal of large object arrays; it is not representative of every event distribution.
All four executable comparisons produced identical SHA-256 output hashes for all three versions.
A further 10,000 generated objects containing duplicate and dotted keys, exceptional values, large integers, and PostHog-specific properties produced identical output hashes in all three modes.
Bluesky exercises real nested JSON and strings, but does not contain PostHog's special property names, so synthetic workloads cover those transformations separately.

ClickHouse measurements used version 26.6.2.158 in Docker on the same host, with the dataset copied into the container.
All three executable-pool functions used the repository's `Raw` format and chunk headers.
Results are medians of seven alternating query runs after one warmup for each of the three binaries:

```sql
SELECT sum(length(CleanBefore(json)))
FROM file('bluesky.json', 'JSONAsString', 'json String')
SETTINGS max_threads = 1, max_block_size = 65536;
-- Repeat with CleanAfter, backed by the optimized executable.
```

All three versions returned `479709047`.
A separate `countIf(CleanBefore(json) != CleanAfter(json))` comparison across the million rows returned zero.
These timings include file parsing and UDF transport; they do not measure inserts, JSON-column type inference, or production concurrency.

Microbenchmark results are medians of five alternating runs with `-cpu=1 -benchtime=500ms`.
They measure parser work separately from whole-process memory.

| Workload                                  |   Before | First pass |    Final | Allocations before / final |
| ----------------------------------------- | -------: | ---------: | -------: | -------------------------: |
| Bluesky, 10,000 rows                      | 16.10 ms |    7.30 ms |  4.76 ms |                  301 / 268 |
| Transformation fixture, 256 rows          | 396.8 µs |   247.3 µs | 205.0 µs |                  1,024 / 0 |
| Clean object                              | 378.4 ns |   229.3 ns | 138.7 ns |                      0 / 0 |
| Wide object, 256 keys                     | 17.96 µs |   17.36 µs | 13.86 µs |                      0 / 0 |
| Dotted object, 256 keys                   | 42.55 µs |   40.72 µs | 25.63 µs |                     19 / 0 |
| Escaped string                            | 27.23 µs |   16.24 µs | 15.70 µs |                      1 / 1 |
| Large discarded payload                   | 581.7 µs |   244.2 µs | 127.7 µs |                  4,139 / 0 |
| Temporary payload filtered from event     | 10.27 µs |    5.30 µs |  2.90 µs |                      9 / 0 |
| Feature flags and exception normalization | 707.0 ns |   512.7 ns | 417.5 ns |                      1 / 1 |

The first pass removed discarded-value allocations, per-row input copies, redundant traversals, and oversized I/O buffers.
Repeated CPU profiles then identified depth-counter updates, scalar recursion, string classification, recycling, and root-key hashing as remaining costs.
The final version passes depth explicitly, skips no-op scalar cleanup while preserving depth checks, classifies string bytes with a 256-byte table, avoids redundant copies, and replaces the fixed discard map with a string switch.
A bounded entry-buffer cache removes repeated dotted-expansion allocations: allocated bytes for the dotted workload fell from 37,972 to approximately 5 per row, amortizing initial buffer allocation, with zero allocations after warmup.
The final Bluesky CPU profile attributes approximately 31% of samples to string parsing, 10% to recycling, and 7% to duplicate checking, including callees.
Two portable eight-byte string-scanning experiments were rejected because they did not improve Bluesky and slowed escaped strings or small objects.

Validation covered the module's unit tests, race detector, `go vet`, both Linux architecture builds, and the ClickHouse stateless fixtures, including quarantine-to-JSON casts.
Temporary differential fuzzing against the baseline compared output bytes and error acceptance across all three modes for approximately 12 million inputs during the first pass, then 988,086 additional generated inputs on the final implementation.
Regression tests cover malformed discarded values, duplicate handling in wide objects, every string byte at multiple offsets, dotted expansion at the depth boundary, escaped rows exceeding the I/O buffer, truncated chunks, processor recovery, and retained-memory limits.
The buffer-reuse test alternates dotted-object widths and verifies exact output, cleared references, the cache bound, and release after a small row.

These local measurements should be repeated on deployment hardware before estimating fleet capacity.
