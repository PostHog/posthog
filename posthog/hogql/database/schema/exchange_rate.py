from posthog.hogql.database.models import (
    StringDatabaseField,
    DateDatabaseField,
    DecimalDatabaseField,
    Table,
    FieldOrTable,
)


class ExchangeRateTable(Table):
    fields: dict[str, FieldOrTable] = {
        "currency": StringDatabaseField(name="currency", nullable=False),
        "date": DateDatabaseField(name="date", nullable=False),
        "rate": DecimalDatabaseField(name="rate", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "exchange_rate"

    def to_printed_hogql(self):
        return "exchange_rate"
