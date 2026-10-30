# ClickHouse reads `clickhouse_metrics` with `input_format_avro_allow_missing_fields = 1`, so a field
# capture stops sending is read as the default. A NULL `series_fingerprint` makes the metrics4 MV drop
# the row, and a type mismatch makes `kafka_skip_broken_messages` skip the block. Neither raises.

import re
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AVRO_SCHEMA_RS = REPO_ROOT / "rust/capture-logs/src/metrics_avro_schema.rs"
KAFKA_TABLE_HCL = REPO_ROOT / "posthog/clickhouse/hcl/roles/apm/shared/metrics4.hcl"
KAFKA_TABLE = "kafka_metrics_avro4"

# The ClickHouse column types that read each Avro type correctly.
AVRO_TO_CLICKHOUSE: dict[str, set[str]] = {
    "string": {"String"},
    "bytes": {"String"},
    "int": {"Int32"},
    "long": {"Int64"},
    "long/timestamp-micros": {"DateTime64(6)"},
    "double": {"Float64"},
    "boolean": {"UInt8", "Bool"},
    "array<double>": {"Array(Float64)"},
    "array<long>": {"Array(Int64)"},
    "map<string>": {"Map(String, String)"},
}


def avro_fields(schema_rs: str) -> dict[str, str]:
    schema = json.loads(schema_rs[schema_rs.index('r#"') + 3 : schema_rs.index('"#')])
    return {field["name"]: _avro_type(field["type"]) for field in schema["fields"]}


def _avro_type(avro_type: object) -> str:
    if isinstance(avro_type, list):
        (non_null,) = [t for t in avro_type if t != "null"]
        return _avro_type(non_null)
    if isinstance(avro_type, str):
        return avro_type
    assert isinstance(avro_type, dict)
    if "logicalType" in avro_type:
        return f"{avro_type['type']}/{avro_type['logicalType']}"
    if avro_type["type"] == "array":
        return f"array<{avro_type['items']}>"
    if avro_type["type"] == "map":
        return f"map<{avro_type['values']}>"
    return avro_type["type"]


def kafka_table_columns(hcl: str, table: str) -> dict[str, str]:
    block = hcl[hcl.index(f'table "{table}" {{') :]
    block = block[: block.index('engine "kafka"')]
    columns = re.findall(r'column "(\w+)" \{ type = "([^"]+)" \}', block)
    return {name: _strip_nullable(column_type) for name, column_type in columns}


def _strip_nullable(column_type: str) -> str:
    match = re.fullmatch(r"Nullable\((.+)\)", column_type)
    return match.group(1) if match else column_type


def contract_errors(fields: dict[str, str], columns: dict[str, str]) -> list[str]:
    errors = [f"Avro field {name!r} has no column in {KAFKA_TABLE}" for name in sorted(fields.keys() - columns.keys())]
    errors += [f"{KAFKA_TABLE} column {name!r} has no Avro field" for name in sorted(columns.keys() - fields.keys())]
    for name in sorted(fields.keys() & columns.keys()):
        allowed = AVRO_TO_CLICKHOUSE.get(fields[name], set())
        if columns[name] not in allowed:
            errors.append(f"{name!r}: Avro {fields[name]} cannot be read as {columns[name]}")
    return errors


def test_capture_avro_schema_matches_the_clickhouse_kafka_table() -> None:
    fields = avro_fields(AVRO_SCHEMA_RS.read_text())
    columns = kafka_table_columns(KAFKA_TABLE_HCL.read_text(), KAFKA_TABLE)

    assert "series_fingerprint" in fields
    assert contract_errors(fields, columns) == []
