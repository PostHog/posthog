from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UnknownDatabaseField,
)

from posthog.clickhouse.preaggregation.web_vitals_paths_preaggregated_sql import (
    DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE,
)


class WebVitalsPathsPreaggregatedTable(Table):
    description: str = (
        "Pre-aggregated per-path Core Web Vitals quantiles (INP, LCP, CLS, FCP), computed per precompute job and used "
        "internally by the web analytics product. Each metric column is an AggregateFunction(quantiles) state that must be merged."
    )
    # Mirrors `WebStatsPreaggregatedTable` / `WebOverviewPreaggregatedTable`:
    # deterministic replica selection via `load_balancing="in_order"` for
    # read-your-writes, and shard pruning via `optimize_skip_unused_shards=1`
    # since the table is sharded by `sipHash64(job_id)` and the read filters
    # `job_id IN (...)`.
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the precompute job that produced this row; reads filter by it."
        ),
        "time_window_start": DateTimeDatabaseField(
            name="time_window_start", description="Start of the time window this aggregated row covers."
        ),
        "path": StringDatabaseField(name="path", description="Page path these web vitals quantiles aggregate."),
        # One AggregateFunction(quantiles(0.75,0.9,0.99), Float64) column per
        # metric; the read picks the column for the queried metric.
        "inp_quantiles_state": UnknownDatabaseField(
            name="inp_quantiles_state",
            description="AggregateFunction(quantiles) state for INP (Interaction to Next Paint), in ms; merge to read.",
        ),
        "lcp_quantiles_state": UnknownDatabaseField(
            name="lcp_quantiles_state",
            description="AggregateFunction(quantiles) state for LCP (Largest Contentful Paint), in ms; merge to read.",
        ),
        "cls_quantiles_state": UnknownDatabaseField(
            name="cls_quantiles_state",
            description="AggregateFunction(quantiles) state for CLS (Cumulative Layout Shift), unitless; merge to read.",
        ),
        "fcp_quantiles_state": UnknownDatabaseField(
            name="fcp_quantiles_state",
            description="AggregateFunction(quantiles) state for FCP (First Contentful Paint), in ms; merge to read.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_vitals_paths_preaggregated"
