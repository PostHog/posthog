from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

DEVICE_BROWSER_FIELDS = {
    "browser": StringDatabaseField(name="browser", nullable=True),
    "os": StringDatabaseField(name="os", nullable=True),
    "viewport_width": IntegerDatabaseField(name="viewport_width", nullable=True),
    "viewport_height": IntegerDatabaseField(name="viewport_height", nullable=True),
}

GEOIP_FIELDS = {
    "country_code": StringDatabaseField(name="country_code", nullable=True),
    "city_name": StringDatabaseField(name="city_name", nullable=True),
    "region_code": StringDatabaseField(name="region_code", nullable=True),
    "region_name": StringDatabaseField(name="region_name", nullable=True),
}

UTM_FIELDS = {
    "utm_source": StringDatabaseField(name="utm_source", nullable=True),
    "utm_medium": StringDatabaseField(name="utm_medium", nullable=True),
    "utm_campaign": StringDatabaseField(name="utm_campaign", nullable=True),
    "utm_term": StringDatabaseField(name="utm_term", nullable=True),
    "utm_content": StringDatabaseField(name="utm_content", nullable=True),
    "referring_domain": StringDatabaseField(name="referring_domain", nullable=True),
}

ATTRIBUTION_FIELDS = {
    "has_gclid": BooleanDatabaseField(name="has_gclid", nullable=True),
    "has_gad_source_paid_search": BooleanDatabaseField(name="has_gad_source_paid_search", nullable=True),
    "has_fbclid": BooleanDatabaseField(name="has_fbclid", nullable=True),
}

PATH_FIELDS = {
    "entry_pathname": StringDatabaseField(name="entry_pathname", nullable=True),
    "end_pathname": StringDatabaseField(name="end_pathname", nullable=True),
}

SHARED_SCHEMA_FIELDS = {
    **DEVICE_BROWSER_FIELDS,
    **GEOIP_FIELDS,
    **UTM_FIELDS,
    **ATTRIBUTION_FIELDS,
    **PATH_FIELDS,
    "mat_metadata_loggedIn": BooleanDatabaseField(name="mat_metadata_loggedIn", nullable=True),
    "mat_metadata_backend": StringDatabaseField(name="mat_metadata_backend", nullable=True),
}


# Web stats daily specific fields
WEB_STATS_SPECIFIC_FIELDS = {
    "pathname": StringDatabaseField(name="pathname", nullable=True),
}

# Web bounces daily specific fields (session calculations: bounce and duration)
WEB_BOUNCES_SPECIFIC_FIELDS = {
    "bounces_count_state": DatabaseField(name="bounces_count_state"),
    "total_session_duration_state": DatabaseField(name="total_session_duration_state"),
    "total_session_count_state": DatabaseField(name="total_session_count_state"),
}


# Base table fields present in all tables
web_preaggregated_base_fields = {
    "period_bucket": DateTimeDatabaseField(name="period_bucket"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "host": StringDatabaseField(name="host"),
    "device_type": StringDatabaseField(name="device_type"),
}


web_preaggregated_base_aggregation_fields = {
    "persons_uniq_state": DatabaseField(name="persons_uniq_state"),
    "pageviews_count_state": DatabaseField(name="pageviews_count_state"),
    "sessions_uniq_state": DatabaseField(name="sessions_uniq_state"),
}


class WebStatsDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_STATS_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_stats_daily"

    def to_printed_hogql(self):
        return "web_stats_daily"


class WebBouncesDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_BOUNCES_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_bounces_daily"

    def to_printed_hogql(self):
        return "web_bounces_daily"


class WebStatsHourlyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_STATS_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_stats_hourly"

    def to_printed_hogql(self):
        return "web_stats_hourly"


class WebBouncesHourlyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_BOUNCES_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_bounces_hourly"

    def to_printed_hogql(self):
        return "web_bounces_hourly"


class WebStatsCombinedTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_STATS_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_stats_combined"

    def to_printed_hogql(self):
        return "web_stats_combined"


class WebBouncesCombinedTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_BOUNCES_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_bounces_combined"

    def to_printed_hogql(self):
        return "web_bounces_combined"


class WebPreAggregatedStatsTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_STATS_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_pre_aggregated_stats"

    def to_printed_hogql(self):
        return "web_pre_aggregated_stats"


class WebPreAggregatedBouncesTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **SHARED_SCHEMA_FIELDS,
        **WEB_BOUNCES_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_pre_aggregated_bounces"

    def to_printed_hogql(self):
        return "web_pre_aggregated_bounces"
