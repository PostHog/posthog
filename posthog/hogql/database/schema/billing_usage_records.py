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
            description="Idempotency key, unique per (team_id, producer_id, usage_key).",
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
        "event_timestamp": DateTimeDatabaseField(
            name="event_timestamp",
            nullable=False,
            description="When the measured usage occurred. Producers stamp it at flush time, so a retry moves it.",
        ),
        "inserted_at": DateTimeDatabaseField(
            name="inserted_at", nullable=False, description="When the usage record was persisted."
        ),
        "dimensions": MapStringDatabaseField(
            name="dimensions", nullable=False, description="Additional producer-defined dimensions."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "billing_usage_records"

    def to_printed_hogql(self):
        return "billing_usage_records"
