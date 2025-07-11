from posthog.hogql.database.models import (
    DatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    Table,
    FieldOrTable,
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
    "time_zone": StringDatabaseField(name="time_zone", nullable=True),
}

UTM_FIELDS = {
    "utm_source": StringDatabaseField(name="utm_source", nullable=True),
    "utm_medium": StringDatabaseField(name="utm_medium", nullable=True),
    "utm_campaign": StringDatabaseField(name="utm_campaign", nullable=True),
    "utm_term": StringDatabaseField(name="utm_term", nullable=True),
    "utm_content": StringDatabaseField(name="utm_content", nullable=True),
    "referring_domain": StringDatabaseField(name="referring_domain", nullable=True),
}

PATH_FIELDS = {
    "entry_pathname": StringDatabaseField(name="entry_pathname", nullable=True),
    "end_pathname": StringDatabaseField(name="end_pathname", nullable=True),
}

SHARED_SCHEMA_FIELDS = {
    **DEVICE_BROWSER_FIELDS,
    **GEOIP_FIELDS,
    **UTM_FIELDS,
    **PATH_FIELDS,
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

# Web sessions specific fields (session-level aggregations)
WEB_SESSIONS_SPECIFIC_FIELDS = {
    "initial_referring_domain": StringDatabaseField(name="initial_referring_domain", nullable=True),
    "initial_utm_source": StringDatabaseField(name="initial_utm_source", nullable=True),
    "initial_utm_medium": StringDatabaseField(name="initial_utm_medium", nullable=True),
    "initial_utm_campaign": StringDatabaseField(name="initial_utm_campaign", nullable=True),
    "initial_utm_term": StringDatabaseField(name="initial_utm_term", nullable=True),
    "initial_utm_content": StringDatabaseField(name="initial_utm_content", nullable=True),
    "initial_browser": StringDatabaseField(name="initial_browser", nullable=True),
    "initial_os": StringDatabaseField(name="initial_os", nullable=True),
    "initial_device_type": StringDatabaseField(name="initial_device_type", nullable=True),
    "initial_viewport_width": IntegerDatabaseField(name="initial_viewport_width", nullable=True),
    "initial_viewport_height": IntegerDatabaseField(name="initial_viewport_height", nullable=True),
    "initial_geoip_country_code": StringDatabaseField(name="initial_geoip_country_code", nullable=True),
    "initial_geoip_subdivision_1_code": StringDatabaseField(name="initial_geoip_subdivision_1_code", nullable=True),
    "initial_geoip_subdivision_1_name": StringDatabaseField(name="initial_geoip_subdivision_1_name", nullable=True),
    "initial_geoip_subdivision_city_name": StringDatabaseField(
        name="initial_geoip_subdivision_city_name", nullable=True
    ),
    "entry_pathname": StringDatabaseField(name="entry_pathname", nullable=True),
    "end_pathname": StringDatabaseField(name="end_pathname", nullable=True),
    "total_session_duration_state": DatabaseField(name="total_session_duration_state"),
    "total_session_count_state": DatabaseField(name="total_session_count_state"),
    "bounces_count_state": DatabaseField(name="bounces_count_state"),
}


# Base table fields present in all tables
web_preaggregated_base_fields = {
    "period_bucket": DateTimeDatabaseField(name="period_bucket"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "host": StringDatabaseField(name="host"),
    "device_type": StringDatabaseField(name="device_type"),
    "updated_at": DateTimeDatabaseField(name="updated_at"),
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


class WebSessionsDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **WEB_SESSIONS_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_sessions_daily"

    def to_printed_hogql(self):
        return "web_sessions_daily"


class WebSessionsHourlyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        **WEB_SESSIONS_SPECIFIC_FIELDS,
    }

    def to_printed_clickhouse(self, context):
        return "web_sessions_hourly"

    def to_printed_hogql(self):
        return "web_sessions_hourly"
