# ClickHouse utility UDFs

`JSONCleanPostHogEventProperties` groups `$feature/<key>` event properties into `$feature_flags`.
Before emitting JSON for insertion, it sorts the keys in `$feature_flags` alphabetically using case-sensitive string order.
This also applies to existing `$feature_flags` objects, after cleanup resolves duplicates and expands dotted keys.
Flag values and person-property ordering follow the existing cleanup rules.

Invalid scalar and array `$feature_flags` values are replaced with an empty map and retained in
`$unparseable_properties`, alongside other invalid complex properties. This keeps malformed
map values from failing insertion into the typed JSON column while preserving unrelated properties.

See [the utility UDF README](../../clickhouse-udfs/util/README.md) for build and integration-test commands.
The utility module and CI use Go 1.27.1, declared in `clickhouse-udfs/util/go.mod`.
Rebuild all utilities for Linux amd64 and arm64 with `./scripts/build.sh` whenever this version changes; CI verifies the checked-in binaries.
Changes to `posthog/user_scripts` no longer dispatch the separate UDF publishing workflow on pushes to master.

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

### `decompress(data, codec)`

Returns the exact decompressed bytes as a ClickHouse `String`, including NUL, newlines, and non-UTF-8 bytes.
Both inputs are regular SQL arguments, so the codec can vary between rows in an `executable_pool`.
The worker uses RowBinary transport with row-count headers and flushes after each chunk, allowing ClickHouse to reuse it across blocks and queries.
See [ClickHouse's executable UDF documentation](https://clickhouse.com/docs/reference/functions/regular-functions/udf) for the argument and pool protocol.

| Codec             | Input                                                                  |
| ----------------- | ---------------------------------------------------------------------- |
| `GZIP`            | GZIP stream, including concatenated members.                           |
| `ZSTD`            | Zstandard frames, including concatenated frames.                       |
| `LZ4`             | Standard LZ4 frames.                                                   |
| `LZ4Block`        | Raw LZ4 block without a size prefix.                                   |
| `LZ4SizePrefixed` | Four-byte little-endian uncompressed size followed by a raw LZ4 block. |

Names are case-insensitive. An empty codec auto-detects GZIP, ZSTD, or framed LZ4, including ZSTD/LZ4 streams with leading skippable metadata frames.
Raw and size-prefixed blocks require an explicit codec because they have no identifying magic bytes.
`LZ4` always means the standard frame format; it does not select the replay envelope.

```sql
SELECT decompress(unhex('170000006068656c6c6f200600d06f2068656c6c6f2068656c6c6f'), 'LZ4SizePrefixed');
-- hello hello hello hello

SELECT decompress(compressed_body, 'ZSTD') FROM messages;
SELECT decompress(base64Decode(encoded_body), '') FROM messages;
```

The replay producer in `rust/capture/src/serialization/mod.rs` uses `LZ4SizePrefixed` and marks those Kafka values with `content-encoding: lz4`.
Read the message value into a raw `String`, decompress it, then parse its JSON.
Kafka record-batch compression is handled by the Kafka client separately.
The function does not pass through uncompressed messages: select which rows need decoding using the message's encoding metadata.
When using `if` to mix compressed and plain rows, set `short_circuit_function_evaluation = 'force_enable'` so the UDF only receives the compressed branch.

Each compressed input is limited to 65 MiB and each decoded value to 64 MiB.
The extra input allowance accommodates compression overhead near the output limit.
Invalid frames, unsupported codecs, truncated transport, size-limit violations, and incorrect envelope sizes fail the query.
Framed codec checksums are validated when present; raw LZ4 blocks have no checksum, so a damaged block that still decodes cannot always be detected.
A size-prefixed block must produce exactly the declared number of bytes.

Workers reuse GZIP and LZ4 readers, the ZSTD decoder, and input/output buffers.
ZSTD uses `DecodeAll` to decode directly into a reusable slice.
Input and output transport buffers are 64 KiB each, down from 4 MiB each in the archived implementation.
Buffers retain their high-water capacity for the worker's lifetime, and each codec can retain separate output storage; the value limit is not a total worker-memory limit.
`LZ4Block` reserves the full 64 MiB output capacity because it has no size metadata; `LZ4SizePrefixed` grows its output buffer to the declared size instead.

The build script, architecture launcher, unversioned function configuration, deployment manifests, and existing utility-UDF CI include the decompressor.
Installing those artifacts makes the function available; this change does not alter Kafka table definitions or materialized views.

Run its unit tests and repeat the synthetic decoding benchmarks from `clickhouse-udfs/util`:

```sh
go test ./cmd/decompress_udf -timeout 30s
go test -run '^$' -bench BenchmarkDecompress -benchmem -cpu=1 -count=3 ./cmd/decompress_udf
```

#### Decompression measurements, September 10, 2026

Baseline: archived `PostHog/clickhouse-util-udfs` commit `92a3dd0c0ce81adada0440144acbdf12ef5beec2`.
Both implementations used Go 1.27.1 on an Apple M4 Pro, macOS arm64, with identical compression-library versions.
The microbenchmark repeats synthetic JSON to make 1 KiB and 64 KiB payloads and reuses one processor after warmup.
Results below are medians of three alternating before/after runs with `-cpu=1 -benchtime=200ms`.

| Workload     | Before    | After     | Speedup | Allocated bytes per row, before / after |
| ------------ | --------- | --------- | ------- | --------------------------------------- |
| GZIP, 1 KiB  | 2,616 ns  | 715 ns    | 3.66×   | 41,256 / 24                             |
| GZIP, 64 KiB | 15,841 ns | 12,764 ns | 1.24×   | 41,256 / 24                             |
| ZSTD, 1 KiB  | 1,489 ns  | 1,312 ns  | 1.13×   | 72 / 0                                  |
| ZSTD, 64 KiB | 20,234 ns | 19,198 ns | 1.05×   | 72 / 0                                  |

LZ4 reader reuse reduces allocations from 488 to 136 bytes per row.
Raw LZ4 decoding uses the same library primitive as before; its decoding speed is effectively unchanged.
The new size-prefixed variant avoids reserving a full 64 MiB buffer for a small block.

Whole-query GZIP measurements used ClickHouse 26.6.2.158 in Docker on the same host.
The baseline used `executable`; the new function used `executable_pool` with chunk headers.
Each result is the median of five alternating measurements after one warmup, using `max_threads=1` and `max_block_size=8192`.

| Workload             | Before | After  | Speedup |
| -------------------- | ------ | ------ | ------- |
| 100,000 rows × 1 KiB | 432 ms | 110 ms | 3.93×   |
| 10,000 rows × 64 KiB | 714 ms | 464 ms | 1.54×   |

Queries summed `length(decompress(materialize(unhex(payload_hex)), materialize('GZIP')))` over `numbers(row_count)` to prevent constant folding.
Separate byte-for-byte comparisons found zero differing rows for both workloads.
These highly compressible, repeated payloads measure decoding and UDF transport, not Kafka ingestion, JSON parsing, or production capacity.

#### Codec dispatch and native Zstandard follow-up

Codec dispatch uses `strings.EqualFold`, avoiding an uppercase-string allocation for mixed-case codec names.
For `LZ4SizePrefixed` on the 1 KiB synthetic workload, median decoding time fell from 92.39 ns to 58.67 ns, a 36.5% reduction.
Allocated bytes fell from 16 to zero per row. These are three-sample medians with `-cpu=1 -benchtime=500ms` on the same macOS arm64 host.
The existing round-trip cases cover original, lowercase, and uppercase codec names.

A separate benchmark compared the Go processor with a direct CGO call to `ZSTD_decompressDCtx`.
It reused a decoder context and a 64 MiB output buffer on both sides, included the CGO call overhead, and verified identical output before timing.
Compression and warmup were excluded; the two decoders received identical frames from the Go encoder at its default compression level.
Payloads contained repeated text, deterministic varied event text, or pseudorandom bytes at 1 KiB, 64 KiB, and 1 MiB.
Text was truncated to the exact benchmark size; no JSON parsing was performed.

Linux results used Go 1.27.1, klauspost/compress v1.19.1, Debian Bookworm libzstd 1.5.4, and glibc 2.36 in an arm64 Docker container on the Apple M4 Pro.
Values below are three-sample medians with `-cpu=1 -benchtime=200ms`.

| Input              | Size   | Go decoder | Native via CGO | Native throughput / Go |
| ------------------ | ------ | ---------- | -------------- | ---------------------- |
| Varied event text  | 1 KiB  | 2.437 µs   | 2.003 µs       | 1.22×                  |
| Varied event text  | 64 KiB | 33.445 µs  | 23.549 µs      | 1.42×                  |
| Varied event text  | 1 MiB  | 472.654 µs | 336.296 µs     | 1.41×                  |
| Repeated text      | 64 KiB | 20.042 µs  | 5.082 µs       | 3.94×                  |
| Pseudorandom bytes | 64 KiB | 3.656 µs   | 4.023 µs       | 0.91×                  |
| Pseudorandom bytes | 1 MiB  | 65.406 µs  | 68.503 µs      | 0.95×                  |

On macOS arm64 with libzstd 1.5.7, native throughput was 1.18–1.31× Go's for varied event text, and 4.72× for the repeated 64 KiB input.
That repeated input compressed to only 77 bytes; its speedup should not be treated as representative.
The macOS and Linux results use different library versions and execution environments, so they do not isolate a libc or version effect.
Neither run measures production CPUs, ClickHouse transport, Kafka ingestion, or concurrent queries.
Go allocation counters do not include C allocations.

Both implementations passed checks for valid and empty frames, unknown content size, concatenated frames, skippable metadata, checksum errors, truncated frames, and output limits.
This is a bounded compatibility check, not an exhaustive audit; the benchmark's direct native API does not implement every policy of the Go UDF, including its window-size restriction.

Native Zstandard is not integrated into the UDF. Both Linux artifacts still build with `CGO_ENABLED=0` and contain no native Zstandard dependency.
A direct C binding requires CGO and a target C toolchain/library. Disabling CGO excludes files importing `C`; it does not automatically select another decoder.
Dynamic native libraries also introduce target ABI and library-version dependencies. See the [Go CGO documentation](https://pkg.go.dev/cmd/cgo).
