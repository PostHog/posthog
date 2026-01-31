# JSON Remove Duplicate Keys UDF

This repository provides a ClickHouse executable UDF named `JSONDropKeys` that deduplicates JSON object keys in a string payload while preserving row order.

Rules

- For duplicate keys, keep the first value that is not `null` and not an empty string.
- If all values are empty strings, keep the last occurrence.
- Nested objects/arrays are processed recursively.
- Input/output format is `Raw` with one JSON string per row.
- The UDF exits with a descriptive error on malformed JSON input.
- Keys containing dots are treated as paths (e.g. `a.b` is merged into `{ "a": { "b": ... } }`).
- Integer values outside the signed 64-bit range are converted to strings.

Repository layout

- `cmd/json_drop_keys_udf/main.go`: Go UDF implementation.
- `udf/JSONDropKeys_function.xml`: ClickHouse executable UDF definition.
- `udf/udf_config.xml`: ClickHouse config to load executable UDF definitions.
- `scripts/build.sh`: CGO-disabled linux binaries for amd64/arm64.
- `scripts/integration_test.sh`: Docker Compose integration test.
- `testdata/`: input/expected fixtures and random samples.

Build

```sh
scripts/build.sh
```

Install (ClickHouse server)

1. Copy the binary to the ClickHouse user scripts directory:

```sh
sudo cp bin/json_drop_keys_udf-linux-amd64 /var/lib/clickhouse/user_scripts/json_drop_keys_udf
sudo chmod +x /var/lib/clickhouse/user_scripts/json_drop_keys_udf
```

2. Copy the UDF definition file (name must end with `_function.xml`):

```sh
sudo cp udf/JSONDropKeys_function.xml /etc/clickhouse-server/user_defined/JSONDropKeys_function.xml
```

3. Ensure ClickHouse loads executable UDF configs:

```sh
sudo cp udf/udf_config.xml /etc/clickhouse-server/config.d/udf_config.xml
```

4. Restart ClickHouse:

```sh
sudo systemctl restart clickhouse-server
```

Integration test (Docker Compose)

```sh
scripts/integration_test.sh
```

Performance benchmark

```sh
go build -o bin/json_drop_keys_udf ./cmd/json_drop_keys_udf
go run ./cmd/perf_bench -target-bytes $((512<<20)) -depth 5 -width 8 -dup 4
```

Example

```sql
SELECT JSONDropKeys('{"a":null,"a":"x","b":""}');
```

Result:

```json
{ "a": "x", "b": "" }
```
