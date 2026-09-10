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
    "browser": StringDatabaseField(name="browser", nullable=True, description="Browser name of the session's device."),
    "os": StringDatabaseField(name="os", nullable=True, description="Operating system name of the session's device."),
    "viewport_width": IntegerDatabaseField(
        name="viewport_width", nullable=True, description="Browser viewport width in CSS pixels."
    ),
    "viewport_height": IntegerDatabaseField(
        name="viewport_height", nullable=True, description="Browser viewport height in CSS pixels."
    ),
}

GEOIP_FIELDS = {
    "country_code": StringDatabaseField(
        name="country_code", nullable=True, description="GeoIP-resolved ISO country code (e.g. 'US')."
    ),
    "city_name": StringDatabaseField(name="city_name", nullable=True, description="GeoIP-resolved city name."),
    "region_code": StringDatabaseField(
        name="region_code", nullable=True, description="GeoIP-resolved region/subdivision code."
    ),
    "region_name": StringDatabaseField(name="region_name", nullable=True, description="GeoIP-resolved region name."),
}

UTM_FIELDS = {
    "utm_source": StringDatabaseField(
        name="utm_source", nullable=True, description="Session's initial utm_source attribution value."
    ),
    "utm_medium": StringDatabaseField(
        name="utm_medium", nullable=True, description="Session's initial utm_medium attribution value."
    ),
    "utm_campaign": StringDatabaseField(
        name="utm_campaign", nullable=True, description="Session's initial utm_campaign attribution value."
    ),
    "utm_term": StringDatabaseField(
        name="utm_term", nullable=True, description="Session's initial utm_term attribution value."
    ),
    "utm_content": StringDatabaseField(
        name="utm_content", nullable=True, description="Session's initial utm_content attribution value."
    ),
    "referring_domain": StringDatabaseField(
        name="referring_domain", nullable=True, description="Session's initial referring domain ('$direct' if none)."
    ),
}

ATTRIBUTION_FIELDS = {
    "has_gclid": BooleanDatabaseField(
        name="has_gclid", nullable=True, description="Whether the session arrived with a Google Ads gclid parameter."
    ),
    "has_gad_source_paid_search": BooleanDatabaseField(
        name="has_gad_source_paid_search",
        nullable=True,
        description="Whether the session's gad_source indicates Google paid search.",
    ),
    "has_fbclid": BooleanDatabaseField(
        name="has_fbclid",
        nullable=True,
        description="Whether the session arrived with a Meta/Facebook fbclid parameter.",
    ),
}

PATH_FIELDS = {
    "entry_pathname": StringDatabaseField(
        name="entry_pathname", nullable=True, description="Pathname of the first pageview in the session."
    ),
    "end_pathname": StringDatabaseField(
        name="end_pathname", nullable=True, description="Pathname of the last pageview in the session."
    ),
}

SHARED_SCHEMA_FIELDS = {
    **DEVICE_BROWSER_FIELDS,
    **GEOIP_FIELDS,
    **UTM_FIELDS,
    **ATTRIBUTION_FIELDS,
    **PATH_FIELDS,
    "mat_metadata_loggedIn": BooleanDatabaseField(
        name="mat_metadata_loggedIn",
        nullable=True,
        description="Materialized session metadata: whether the user was logged in.",
    ),
    "mat_metadata_backend": StringDatabaseField(
        name="mat_metadata_backend",
        nullable=True,
        description="Materialized session metadata: backend/framework identifier.",
    ),
}


# Web stats daily specific fields
WEB_STATS_SPECIFIC_FIELDS = {
    "pathname": StringDatabaseField(
        name="pathname", nullable=True, description="Page path this stats row is broken down by."
    ),
}

# Web bounces daily specific fields (session calculations: bounce and duration)
WEB_BOUNCES_SPECIFIC_FIELDS = {
    "bounces_count_state": DatabaseField(
        name="bounces_count_state",
        description="AggregateFunction state for bounced session count; merge with sumMerge to read.",
    ),
    "total_session_duration_state": DatabaseField(
        name="total_session_duration_state",
        description="AggregateFunction state for total session duration in seconds; merge with sumMerge to read.",
    ),
    "total_session_count_state": DatabaseField(
        name="total_session_count_state",
        description="AggregateFunction state for total session count; merge with sumMerge to read.",
    ),
}


# Base table fields present in all tables
web_preaggregated_base_fields = {
    "period_bucket": DateTimeDatabaseField(
        name="period_bucket", description="Start of the time bucket (day) this pre-aggregated row covers."
    ),
    "team_id": IntegerDatabaseField(name="team_id"),
    "host": StringDatabaseField(name="host", description="Hostname the traffic was served from."),
    "device_type": StringDatabaseField(name="device_type", description="Device type (e.g. 'Desktop', 'Mobile')."),
}


web_preaggregated_base_aggregation_fields = {
    "persons_uniq_state": DatabaseField(
        name="persons_uniq_state",
        description="AggregateFunction(uniq) state for unique persons; merge with uniqMerge to read.",
    ),
    "pageviews_count_state": DatabaseField(
        name="pageviews_count_state",
        description="AggregateFunction(sum) state for pageview count; merge with sumMerge to read.",
    ),
    "sessions_uniq_state": DatabaseField(
        name="sessions_uniq_state",
        description="AggregateFunction(uniq) state for unique sessions; merge with uniqMerge to read.",
    ),
}


class WebPreAggregatedStatsTable(Table):
    description: str = (
        "Pre-aggregated daily web analytics stats bucketed by dimensions (path, device, geo, UTM, etc.), "
        "used internally by the web analytics product. Metric columns are AggregateFunction states that must be merged."
    )
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
    description: str = (
        "Pre-aggregated daily web analytics session metrics (bounce rate and session duration) bucketed by dimensions, "
        "used internally by the web analytics product. Metric columns are AggregateFunction states that must be merged."
    )
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
