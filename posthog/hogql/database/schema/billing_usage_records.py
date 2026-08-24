from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    MapStringDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)


class BillingUsageRecordsTable(Table):
    """Usage records emitted by PostHog product services.

    HogQL applies its standard ``team_id`` guard to this table, so records are
    visible only in the project that produced them.

    Rows deduplicate on ``(team_id, toDate(timestamp), producer_id, usage_key, record_id)``, and
    the collapse only happens on merge. Read with ``argMax(quantity, timestamp)`` grouped by that
    key; a plain ``sum(quantity)`` counts duplicates that have not merged yet, and HogQL rejects
    ``FINAL``.
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
        "mode": StringDatabaseField(
            name="mode", nullable=False, description="Whether this record is a delta or snapshot."
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
        "dimensions": MapStringDatabaseField(
            name="dimensions", nullable=False, description="Additional producer-defined dimensions."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "billing_usage_records"

    def to_printed_hogql(self):
        return "billing_usage_records"
