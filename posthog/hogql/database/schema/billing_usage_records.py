from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


class BillingUsageRecordsTable(Table):
    """Usage records emitted by PostHog product services.

    HogQL applies its standard ``team_id`` guard to this table, so records are
    visible only in the project that produced them.

    Rows deduplicate on ``(team_id, toDate(timestamp), producer_id, usage_key, record_id)``, and
    the collapse only happens on merge. ``argMax(quantity, timestamp)`` grouped by that key is the
    exact read, because HogQL rejects ``FINAL``, but ``record_id`` is unique per row, so that
    grouping holds one aggregation state per row and exceeds the per-query memory limit over any
    real range. A plain ``sum(quantity)`` counts un-merged duplicates instead, which overstates a
    total by a fraction of a percent. Prefer the plain sum unless the read is both scoped to a
    small range and required to be exact.
    """

    description: str = "Durable product-usage records emitted by event ingestion, CDP, and feature flags."

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "organization_id": UUIDDatabaseField(
            name="organization_id", nullable=False, description="Organization that owns the project."
        ),
        "record_id": StringDatabaseField(
            name="record_id",
            nullable=False,
            description="Idempotency key, unique per (team_id, toDate(timestamp), producer_id, usage_key).",
        ),
        "producer_id": StringDatabaseField(
            name="producer_id", nullable=False, description="Service that emitted the usage record."
        ),
        "usage_key": StringDatabaseField(
            name="usage_key", nullable=False, description="Kind of product usage being measured."
        ),
        "unit": StringDatabaseField(name="unit", nullable=False, description="Unit used by quantity."),
        "quantity": IntegerDatabaseField(name="quantity", nullable=False, description="Measured usage amount."),
        "timestamp": DateTimeDatabaseField(
            name="timestamp",
            nullable=False,
            description=(
                "When the producer reported the usage. toDate of it is part of the table's sorting "
                "key, so filtering on it is what makes a query cheap."
            ),
        ),
        # `inserted_at` is left out on purpose. It is the engine's version column, so exposing it
        # would offer a second time column that looks interchangeable with `timestamp` but is
        # absent from the sorting key, and filtering on it would read the whole partition.
        # `timestamp` is monotonic per resend, so `argMax(quantity, timestamp)` already picks the
        # row a merge would keep, which is the only thing a reader needed the version column for.
    }

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "billing_usage_records"

    def to_printed_hogql(self) -> str:
        return "billing_usage_records"
