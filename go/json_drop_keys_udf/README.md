# JSON Drop Keys UDF

This repository provides a ClickHouse executable UDF named `JSONDropKeys` that removes specified keys from JSON objects.

Rules

- Takes a const array parameter specifying which keys to drop.
- Nested objects/arrays are processed recursively.
- Keys containing dots are treated as paths (e.g. dropping `a.b` removes `b` from nested object `a`).
- Input/output format is `Raw` with one JSON string per row.
- The UDF exits with a descriptive error on malformed JSON input.

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
scripts/bench_file.sh
```

This downloads a sample dataset and benchmarks throughput (MiB/s).

Example

```sql
SELECT JSONDropKeys(['a', 'b'])('{"id":1,"a":"x","b":"y","c":"z"}');
```

Result:

```json
{ "id": 1, "c": "z" }
```

Dropping nested keys:

```sql
SELECT JSONDropKeys(['props.secret'])('{"id":1,"props":{"secret":"xxx","public":"yyy"}}');
```

Result:

```json
{ "id": 1, "props": { "public": "yyy" } }
```
