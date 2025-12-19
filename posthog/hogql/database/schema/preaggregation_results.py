from posthog.hogql.database.models import (
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE


class PreaggregationResultsTable(Table):
    """
    HogQL schema for the sharded_preaggregation_results table.
    Used for on-demand preaggregation of queries like uniqExact(person_id) GROUP BY day.
    """

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "time_window_start": DateTimeDatabaseField(name="time_window_start"),
        "breakdown_value": StringArrayDatabaseField(name="breakdown_value"),
        # Aggregate state column - using generic DatabaseField since it's an AggregateFunction type
        "uniq_exact_state": DatabaseField(name="uniq_exact_state"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()

    def to_printed_hogql(self):
        return "preaggregation_results"
