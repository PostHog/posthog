# JSONDropKeys performance

`JSONDropKeys` removes selected property paths, including paths through arrays, and expands dotted keys only in objects visited by the filter.
Filtering, duplicate order, numeric text, string escaping, and the scope of dotted expansion remain unchanged.
The implementation retains fastjson's parsing and validation behavior, including validation of discarded values.
Input and output failures now propagate to the executable's exit status.

Ordinary objects write directly from the fastjson tree instead of allocating a second tree.
Objects requiring dotted expansion retain the existing merge algorithm, with scalar nodes referencing parsed values until serialization completes.
The JSON writer consumes byte slices without copying strings or changing escape formatting.

Each executable uses 64 KiB input and output buffers and borrows ordinary input rows from the reader.
Rows larger than the input buffer use an owned slice, with no new row-size limit.
Parser storage resets when its largest input exceeds both 64 KiB and twice the next row's length; output buffers follow the same size rule.
Dotted-object pools clear retained references and release backing arrays whose capacity exceeds 4,096 entries.
Dotted-key maps with more than 4,096 entries do not return to the pool.
These bounds limit individual reusable buffers; they do not cap memory for a currently parsed document.

## Reproducing benchmarks

The [cleaner benchmark instructions](clickhouse-utility-udfs.md#benchmarking-the-cleaner) download the public JSONBench Bluesky dataset.
The same file contains 1,000,000 rows and 480,778,277 bytes, including newlines.
Its SHA-256 is `7beb29f6c036fe784754ff34d68d1f216c6cc89de12155da06f725bdf5c8536e`.
From `clickhouse-udfs/util`:

```sh
mkdir -p /tmp/dropkeys-bench
BENCH_FILE=/tmp/cleaner-bench/sample.json go test -run '^$' -bench BenchmarkDropFixturePaths -benchmem -cpu=1 -count=5 ./cmd/json_drop_keys_udf
go test -run '^$' -bench BenchmarkDropWorkloads -benchmem -cpu=1 -count=5 ./cmd/json_drop_keys_udf
go build -o /tmp/dropkeys-bench/cleaner ./cmd/json_drop_keys_udf
GOMAXPROCS=1 /usr/bin/time -l /tmp/dropkeys-bench/cleaner "['commit.record.text']" < /tmp/cleaner-bench/bluesky.json > /dev/null
```

Keep decompression outside the timed command and compare output hashes before interpreting timings.
On Linux, use `/usr/bin/time -v`, which reports RSS in KiB rather than macOS's bytes.

## Results recorded September 9, 2026

Baseline: `e040ebf295e9d5de24ef3795b01bfa8a120d9c27`, before the JSONDropKeys changes.
Host: Apple M4 Pro, macOS arm64, Go 1.25.5.
Native results use seven alternating runs per version, cached file input, discarded output, and `GOMAXPROCS=1`.
RSS is the median of each run's maximum resident set size, not live heap size.

| Selected keys        | Before |  After | Speedup | Peak RSS before / after |
| -------------------- | -----: | -----: | ------: | ----------------------: |
| `missing`            | 1.65 s | 0.86 s |   1.92× |        30.91 / 4.31 MiB |
| `commit.record.text` | 1.88 s | 0.91 s |   2.07× |        31.66 / 4.33 MiB |
| `commit`             | 1.48 s | 0.39 s |   3.79× |        31.73 / 4.31 MiB |

All three before/after comparisons produced identical output hashes for both the full Bluesky dataset and the generated corpus.

Go microbenchmarks use five runs per binary with `-cpu=1 -benchtime=500ms`.
Allocations are per benchmark operation, with startup allocations amortized and counts rounded by Go.

| Workload                           |    Before |    After | Allocations before / after |
| ---------------------------------- | --------: | -------: | -------------------------: |
| Bluesky, 10,000 rows, missing key  |  15.12 ms |  7.33 ms |                268,177 / 0 |
| Bluesky, 10,000 rows, nested field |  16.83 ms |  8.23 ms |                269,002 / 0 |
| Bluesky, 10,000 rows, subtree      |  14.14 ms |  3.34 ms |                417,509 / 0 |
| Wide object, 256 keys              |  22.04 µs |  9.60 µs |                    512 / 0 |
| Dotted object, 256 keys            |  34.05 µs | 28.52 µs |                  514 / 257 |
| Large discarded payload            | 608.51 µs | 74.06 µs |                 20,481 / 0 |
| Escaped string                     |  22.16 µs | 20.28 µs |                      2 / 0 |

ClickHouse 26.6.2.158 ran in Docker on the same host, with the file copied into the container.
Both versions use the existing `executable` function type, `Raw` format, and parameterized key array.
Medians cover five alternating query runs after one warmup per binary, with `max_threads=1` and `max_block_size=65536`.

| Selected keys        |  Before |   After | Speedup |
| -------------------- | ------: | ------: | ------: |
| `missing`            | 2.066 s | 1.216 s |   1.70× |
| `commit.record.text` | 2.198 s | 1.256 s |   1.75× |
| `commit`             | 2.020 s | 0.700 s |   2.89× |

```sql
SELECT sum(length(DropBefore(['commit.record.text'])(json)))
FROM file('bluesky.json', 'JSONAsString', 'json String')
SETTINGS max_threads=1, max_block_size=65536;
-- Repeat with DropAfter, backed by the optimized executable.
```

A separate `countIf(DropBefore(keys)(json) != DropAfter(keys)(json))` returned zero for each selected key array across all million rows.
These timings include executable startup, file parsing, and UDF transport; ClickHouse RSS was not measured.

The initial CPU profile attributed approximately 36% of samples to copying the parsed document into wrapper nodes.
Direct serialization removes almost all per-row allocations in the Bluesky fixture; occasional parser-pool replenishment still allocates.
An append-based string writer was rejected because it slowed the fixture; byte-oriented writes retained the allocation reduction.
Reprofiling the dotted-object path led to removing copied scalar wrappers there as well.
The final Bluesky profile spends approximately 31% of samples in string writing and 24% in parsing, including callees.

## Validation

Local checks cover Go unit tests, race detection, vet, Linux amd64 and arm64 builds, and ClickHouse stateless fixtures.
Regression tests exercise duplicate dotted merges, expansion scope through arrays, Unicode/control escaping, malformed discarded values, large rows, newline handling, released references, and output errors.
Differential fuzzing compared output bytes and error acceptance against the original implementation for 5,958,210 inputs, then another 4,258,015 after the scalar change.
Whole-file comparisons cover the million-row Bluesky file and 10,000 generated objects.

These measurements do not cover production concurrency or ClickHouse JSON-column inference.
