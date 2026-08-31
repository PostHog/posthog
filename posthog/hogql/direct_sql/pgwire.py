from datetime import date, datetime

import psycopg
from psycopg.types.datetime import DateLoader

MANAGED_WAREHOUSE_CONNECTION_ERROR = (
    "Could not connect to the managed warehouse. Try again, and contact support if the problem persists."
)

POSTGRES_OID_TO_CLICKHOUSE_TYPE: dict[int, str] = {
    16: "Bool",
    20: "Int64",
    21: "Int16",
    23: "Int32",
    26: "UInt32",
    700: "Float32",
    701: "Float64",
    1082: "Date",
    1114: "DateTime",
    1184: "DateTime64(6, 'UTC')",
    1700: "Decimal",
    17: "String",
    19: "String",
    25: "String",
    1042: "String",
    1043: "String",
    114: "String",
    3802: "String",
    2950: "UUID",
    1083: "String",
    1266: "String",
    1186: "String",
    1000: "Array(Bool)",
    1005: "Array(Int16)",
    1007: "Array(Int32)",
    1016: "Array(Int64)",
    1021: "Array(Float32)",
    1022: "Array(Float64)",
    1115: "Array(DateTime)",
    1185: "Array(DateTime64(6, 'UTC'))",
    1182: "Array(Date)",
    1231: "Array(Decimal)",
    1009: "Array(String)",
    1015: "Array(String)",
    2951: "Array(UUID)",
}


def postgres_oid_to_clickhouse_type(oid: int | None) -> str:
    if oid is None:
        return "String"
    return POSTGRES_OID_TO_CLICKHOUSE_TYPE.get(oid, "String")


def postgres_error_to_message(error: Exception) -> str:
    if isinstance(error, psycopg.Error):
        diag = getattr(error, "diag", None)
        message_primary = getattr(diag, "message_primary", None) if diag else None
        message_detail = getattr(diag, "message_detail", None) if diag else None
        if message_primary and message_detail:
            return f"{message_primary} {message_detail}"
        if message_primary:
            return message_primary

    message = str(error).strip()
    if not message:
        return "Postgres query failed."
    return message.splitlines()[0]


def parse_lenient_direct_postgres_date(value: str) -> date:
    trimmed = value.strip()
    try:
        return date.fromisoformat(trimmed)
    except ValueError:
        pass

    normalized = trimmed[:-1] + "+00:00" if trimmed.endswith("Z") else trimmed
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass

    if len(trimmed) >= 10:
        return date.fromisoformat(trimmed[:10])
    raise ValueError(f"Unable to parse date value: {value!r}")


class LenientDirectPostgresDateLoader(DateLoader):
    """Handle non-standard DATE text values returned by DuckDB's Postgres wire."""

    def load(self, data) -> date:
        try:
            return super().load(data)
        except psycopg.DataError as exc:
            try:
                return parse_lenient_direct_postgres_date(bytes(data).decode("utf8", "replace"))
            except ValueError:
                raise exc from None
