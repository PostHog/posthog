from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UnknownDatabaseField,
)

from posthog.clickhouse.preaggregation.web_bounces_dimensional_preaggregated_sql import (
    DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE,
)


class WebBouncesDimensionalPreaggregatedTable(Table):
    description: str = (
        "Pre-aggregated session-grain web analytics metrics over a fixed dimension set (entry/exit path, device, "
        "geo, UTMs, click-id presence), computed per precompute job. Precomputation-framework successor to "
        "`web_pre_aggregated_bounces`. Metric columns are AggregateFunction states that must be merged."
    )
    # Mirrors `WebStatsPathsPreaggregatedTable`: deterministic replica selection via
    # `load_balancing="in_order"` (read-your-writes) and shard pruning via
    # `optimize_skip_unused_shards=1` (sharded by `sipHash64(job_id)`, and the read
    # filters `job_id IN (...)`).
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the precompute job that produced this row; reads filter by it."
        ),
        "period_bucket": DateTimeDatabaseField(
            name="period_bucket",
            description="Hourly UTC bucket on the session's start timestamp. Rows are bucketed in UTC, not the "
            "project timezone.",
        ),
        # Dimensions. `host` and `device_type` come from the event rather than the session, so a session
        # spanning several of either is split across rows; grouping by them can therefore double count a
        # session. Merging the uniq states across those rows is safe.
        "host": StringDatabaseField(name="host"),
        "device_type": StringDatabaseField(name="device_type"),
        "entry_pathname": StringDatabaseField(name="entry_pathname"),
        "end_pathname": StringDatabaseField(name="end_pathname"),
        "browser": StringDatabaseField(name="browser"),
        "os": StringDatabaseField(name="os"),
        "viewport_width": IntegerDatabaseField(name="viewport_width"),
        "viewport_height": IntegerDatabaseField(name="viewport_height"),
        # Session *entry* attribution: these carry the session's initial values, not the emitting event's.
        "referring_domain": StringDatabaseField(name="referring_domain"),
        "utm_source": StringDatabaseField(name="utm_source"),
        "utm_medium": StringDatabaseField(name="utm_medium"),
        "utm_campaign": StringDatabaseField(name="utm_campaign"),
        "utm_term": StringDatabaseField(name="utm_term"),
        "utm_content": StringDatabaseField(name="utm_content"),
        "country_code": StringDatabaseField(name="country_code"),
        "city_name": StringDatabaseField(name="city_name"),
        "region_code": StringDatabaseField(name="region_code"),
        "region_name": StringDatabaseField(name="region_name"),
        # Presence flags only: the click-id values themselves are not stored.
        "has_gclid": BooleanDatabaseField(name="has_gclid"),
        "has_gad_source_paid_search": BooleanDatabaseField(name="has_gad_source_paid_search"),
        "has_fbclid": BooleanDatabaseField(name="has_fbclid"),
        "mat_metadata_backend": StringDatabaseField(name="mat_metadata_backend", nullable=True),
        "mat_metadata_loggedIn": BooleanDatabaseField(name="mat_metadata_loggedIn", nullable=True),
        "persons_uniq_state": UnknownDatabaseField(
            name="persons_uniq_state", description="AggregateFunction(uniq) state for unique persons; merge to read."
        ),
        "sessions_uniq_state": UnknownDatabaseField(
            name="sessions_uniq_state", description="AggregateFunction(uniq) state for unique sessions; merge to read."
        ),
        "pageviews_count_state": UnknownDatabaseField(
            name="pageviews_count_state", description="AggregateFunction(sum) state for pageview count; merge to read."
        ),
        "bounces_count_state": UnknownDatabaseField(
            name="bounces_count_state", description="AggregateFunction(sum) state for bounce count; merge to read."
        ),
        "total_session_duration_state": UnknownDatabaseField(
            name="total_session_duration_state",
            description="AggregateFunction(sum) state for total session duration; merge to read.",
        ),
        "total_session_count_state": UnknownDatabaseField(
            name="total_session_count_state",
            description="AggregateFunction(sum) state for total session count; merge to read.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_bounces_dimensional_preaggregated"
