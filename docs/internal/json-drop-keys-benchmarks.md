# JSONDropKeys benchmarks

The Go benchmarks in `clickhouse-udfs/util/cmd/json_drop_keys_udf/main_test.go` measure
parsing, filtering, and serialization per JSON row. Run them from the repository root:

```sh
go -C clickhouse-udfs/util test ./cmd/json_drop_keys_udf \
  -run '^$' -bench '^BenchmarkProcess' -benchmem -benchtime=1s -count=7 -cpu=1
```

When using the Codex development environment, prefix the command with `.codex/with-flox`.
To select an installed compiler explicitly, pass its executable path instead of `go`.
For example, `.codex/with-flox /usr/local/go/bin/go version` verifies the system compiler.
Use the same compiler and CPU setting for both revisions.

## Workloads

Fixtures live in `clickhouse-udfs/util/cmd/json_drop_keys_udf/testdata/benchmarks/`.
They are synthetic and contain no customer data.

| Benchmark                         | Fixture                                                           | Removed paths                   |
| --------------------------------- | ----------------------------------------------------------------- | ------------------------------- |
| `BenchmarkProcessLine`            | `small.jsonl`: one compact event                                  | `identity`, `properties.secret` |
| `BenchmarkProcessFixture/missing` | `events.jsonl`: 16 events with nested properties and arrays       | `missing`                       |
| `BenchmarkProcessFixture/nested`  | `events.jsonl`                                                    | `properties.secret`             |
| `BenchmarkProcessFixture/subtree` | `events.jsonl`                                                    | `properties`                    |
| `BenchmarkProcessFixture/array`   | `events.jsonl`                                                    | `events.identity`               |
| `BenchmarkProcessFixture/dotted`  | `dotted.jsonl`: dotted names, an array, and an unfiltered sibling | `items.a.b`                     |

Each iteration processes one row, cycling through the fixture. `ns/op`, `B/op`, and
`allocs/op` are per row; `MB/s` uses the average input row size, excluding newlines.
Fixture loading, filter construction, and a warmup pass happen outside the timed region.
These benchmarks measure steady-state buffer reuse, not cold-start allocations or peak RSS.

The fixture benchmark previously reported an entire batch per operation. Its new named
sub-benchmarks report one row per operation; compare revisions using the same benchmark code.

## Custom input

Set `BENCH_FILE` to a JSON Lines file to replace `events.jsonl` for the missing, nested,
subtree, and array workloads. Absolute paths work directly; relative paths resolve from
`clickhouse-udfs/util`. The small and dotted benchmarks keep their dedicated fixtures.

```sh
BENCH_FILE=/tmp/generated-events.jsonl go -C clickhouse-udfs/util test \
  ./cmd/json_drop_keys_udf -run '^$' -bench '^BenchmarkProcessFixture/nested$' \
  -benchmem -benchtime=1s -count=7 -cpu=1
```

For Codex, put the environment assignment after the wrapper:

```sh
.codex/with-flox env BENCH_FILE=/tmp/generated-events.jsonl /usr/local/go/bin/go \
  -C clickhouse-udfs/util test ./cmd/json_drop_keys_udf -run '^$' \
  -bench '^BenchmarkProcessFixture/nested$' -benchmem -benchtime=1s -count=7 -cpu=1
```

Keep custom datasets outside the repository unless they are safe to publish. When comparing
revisions, alternate their execution order and retain every sample. Native benchmark timings
do not include ClickHouse scheduling, transport, or concurrent query load.
