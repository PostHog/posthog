from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class WebBotsPreaggregatedTable(Table):
    description: str = (
        "Hourly bot request counts by crawler, category, host, and path, shared by the bot analytics tiles."
    )
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id", description="Precompute job that owns this row."),
        "time_window_start": DateTimeDatabaseField(name="time_window_start", description="Start of the UTC hour."),
        "bot_name": StringDatabaseField(name="bot_name"),
        "category": StringDatabaseField(name="category"),
        "host": StringDatabaseField(name="host", nullable=True),
        "pathname": StringDatabaseField(name="pathname", nullable=True),
        "requests": IntegerDatabaseField(name="requests", description="Number of requests in this hour."),
        "last_seen": DateTimeDatabaseField(name="last_seen", description="Time of the most recent request."),
    }

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "web_bots_preaggregated"

    def to_printed_hogql(self) -> str:
        return "posthog.web_bots_preaggregated"
