"""
Shared transformation expressions for converting raw property values to typed columns.

These functions generate SQL expressions used by both:
- The Kafka MV (for new events ingested via Kafka)
- The EAV backfill (for historical events)

Using shared functions ensures transformation logic stays consistent and prevents drift.

IMPORTANT: These MUST match HogQL's type conversion behavior exactly.
See posthog/hogql/functions/clickhouse/conversions.py and
posthog/hogql/transforms/property_types.py for the HogQL implementations.
"""


def string_transform(value_expr: str) -> str:
    """Passthrough - raw value as-is."""
    return value_expr


def numeric_transform(value_expr: str) -> str:
    """Convert to Float64, NULL if not a valid number. Matches HogQL toFloat()."""
    return f"accurateCastOrNull({value_expr}, 'Float64')"


def boolean_transform(value_expr: str) -> str:
    """Convert 'true'/'false' (case-sensitive) to 1/0, NULL otherwise. Matches HogQL toBool()."""
    return f"transform(toString({value_expr}), ['true', 'false'], [1, 0], NULL)"


def datetime_transform(value_expr: str) -> str:
    """
    Passthrough - store raw datetime string, convert at query time.

    This matches traditional mat_* column behavior and avoids the timezone
    interpretation problem: if we converted at write time, changing the team's
    timezone would not affect already-stored values, causing inconsistency
    with direct HogQL queries which interpret at query time.

    HogQL applies toDateTime(value, team_timezone) at query time.
    """
    return value_expr
