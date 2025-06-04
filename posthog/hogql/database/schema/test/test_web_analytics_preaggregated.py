from posthog.hogql.database.schema.web_analytics_preaggregated import (
    WebStatsDailyTable,
    WebBouncesDailyTable,
    WebStatsHourlyTable,
    WebBouncesHourlyTable,
    WebStatsCombinedTable,
    WebBouncesCombinedTable,
    SHARED_SCHEMA_FIELDS,
    DEVICE_BROWSER_FIELDS,
    GEOIP_FIELDS,
    UTM_FIELDS,
    ATTRIBUTION_TRACKING_FIELDS,
    PATH_FIELDS,
    WEB_STATS_SPECIFIC_FIELDS,
    WEB_BOUNCES_SPECIFIC_FIELDS,
)


class TestWebAnalyticsPreAggregatedSchema:
    def test_shared_fields_present_in_all_tables(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()
        stats_combined_table = WebStatsCombinedTable()
        bounces_combined_table = WebBouncesCombinedTable()

        for field_name in SHARED_SCHEMA_FIELDS.keys():
            assert (
                field_name in stats_daily_table.fields
            ), f"Shared field '{field_name}' missing from WebStatsDailyTable"
            assert (
                field_name in bounces_daily_table.fields
            ), f"Shared field '{field_name}' missing from WebBouncesDailyTable"
            assert (
                field_name in stats_hourly_table.fields
            ), f"Shared field '{field_name}' missing from WebStatsHourlyTable"
            assert (
                field_name in bounces_hourly_table.fields
            ), f"Shared field '{field_name}' missing from WebBouncesHourlyTable"
            assert (
                field_name in stats_combined_table.fields
            ), f"Shared field '{field_name}' missing from WebStatsCombinedTable"
            assert (
                field_name in bounces_combined_table.fields
            ), f"Shared field '{field_name}' missing from WebBouncesCombinedTable"

    def test_table_specific_fields(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        # Stats table specific fields
        for field_name in WEB_STATS_SPECIFIC_FIELDS.keys():
            assert (
                field_name in stats_daily_table.fields
            ), f"Stats-specific field '{field_name}' missing from WebStatsDailyTable"
            assert (
                field_name in stats_hourly_table.fields
            ), f"Stats-specific field '{field_name}' missing from WebStatsHourlyTable"

        # Bounces table specific fields
        for field_name in WEB_BOUNCES_SPECIFIC_FIELDS.keys():
            assert (
                field_name in bounces_daily_table.fields
            ), f"Bounces-specific field '{field_name}' missing from WebBouncesDailyTable"
            assert (
                field_name in bounces_hourly_table.fields
            ), f"Bounces-specific field '{field_name}' missing from WebBouncesHourlyTable"

        # Verify pathname is only in stats tables
        assert "pathname" in stats_daily_table.fields
        assert "pathname" not in bounces_daily_table.fields
        assert "pathname" in stats_hourly_table.fields
        assert "pathname" not in bounces_hourly_table.fields

        # Verify bounce-specific fields are only in bounces tables
        assert "bounces_count_state" not in stats_daily_table.fields
        assert "total_session_duration_state" not in stats_daily_table.fields
        assert "bounces_count_state" not in stats_hourly_table.fields
        assert "total_session_duration_state" not in stats_hourly_table.fields
        assert "bounces_count_state" in bounces_daily_table.fields
        assert "total_session_duration_state" in bounces_daily_table.fields
        assert "bounces_count_state" in bounces_hourly_table.fields
        assert "total_session_duration_state" in bounces_hourly_table.fields

    def test_device_browser_fields(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        expected_fields = ["browser", "browser_version", "os", "os_version", "viewport_width", "viewport_height"]

        for field in expected_fields:
            assert field in stats_daily_table.fields, f"Device/browser field '{field}' missing from WebStatsDailyTable"
            assert (
                field in bounces_daily_table.fields
            ), f"Device/browser field '{field}' missing from WebBouncesDailyTable"
            assert (
                field in stats_hourly_table.fields
            ), f"Device/browser field '{field}' missing from WebStatsHourlyTable"
            assert (
                field in bounces_hourly_table.fields
            ), f"Device/browser field '{field}' missing from WebBouncesHourlyTable"

    def test_geoip_fields(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        expected_fields = ["country_code", "country_name", "city_name", "region_code", "region_name", "time_zone"]

        for field in expected_fields:
            assert field in stats_daily_table.fields, f"GeoIP field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_daily_table.fields, f"GeoIP field '{field}' missing from WebBouncesDailyTable"
            assert field in stats_hourly_table.fields, f"GeoIP field '{field}' missing from WebStatsHourlyTable"
            assert field in bounces_hourly_table.fields, f"GeoIP field '{field}' missing from WebBouncesHourlyTable"

    def test_attribution_tracking_fields(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        expected_fields = [
            "gclid",
            "gad_source",
            "gclsrc",
            "dclid",
            "gbraid",
            "wbraid",
            "fbclid",
            "msclkid",
            "twclid",
            "li_fat_id",
            "mc_cid",
            "igshid",
            "ttclid",
            "epik",
            "qclid",
            "sccid",
            "_kx",
            "irclid",
        ]

        for field in expected_fields:
            assert field in stats_daily_table.fields, f"Attribution field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_daily_table.fields, f"Attribution field '{field}' missing from WebBouncesDailyTable"
            assert field in stats_hourly_table.fields, f"Attribution field '{field}' missing from WebStatsHourlyTable"
            assert (
                field in bounces_hourly_table.fields
            ), f"Attribution field '{field}' missing from WebBouncesHourlyTable"

    def test_utm_fields(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        expected_fields = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "referring_domain"]

        for field in expected_fields:
            assert field in stats_daily_table.fields, f"UTM field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_daily_table.fields, f"UTM field '{field}' missing from WebBouncesDailyTable"
            assert field in stats_hourly_table.fields, f"UTM field '{field}' missing from WebStatsHourlyTable"
            assert field in bounces_hourly_table.fields, f"UTM field '{field}' missing from WebBouncesHourlyTable"

    def test_path_fields(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        expected_fields = ["entry_pathname", "end_pathname"]

        for field in expected_fields:
            assert field in stats_daily_table.fields, f"Path field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_daily_table.fields, f"Path field '{field}' missing from WebBouncesDailyTable"
            assert field in stats_hourly_table.fields, f"Path field '{field}' missing from WebStatsHourlyTable"
            assert field in bounces_hourly_table.fields, f"Path field '{field}' missing from WebBouncesHourlyTable"

    def test_shared_schema_fields_composition(self):
        expected_field_count = (
            len(DEVICE_BROWSER_FIELDS)
            + len(GEOIP_FIELDS)
            + len(UTM_FIELDS)
            + len(ATTRIBUTION_TRACKING_FIELDS)
            + len(PATH_FIELDS)
        )

        assert (
            len(SHARED_SCHEMA_FIELDS) == expected_field_count
        ), f"SHARED_SCHEMA_FIELDS has {len(SHARED_SCHEMA_FIELDS)} fields, expected {expected_field_count}"

        # Verify all fields from each group are present
        for field in DEVICE_BROWSER_FIELDS:
            assert field in SHARED_SCHEMA_FIELDS, f"Device/browser field '{field}' missing from SHARED_SCHEMA_FIELDS"
        for field in GEOIP_FIELDS:
            assert field in SHARED_SCHEMA_FIELDS, f"GeoIP field '{field}' missing from SHARED_SCHEMA_FIELDS"
        for field in UTM_FIELDS:
            assert field in SHARED_SCHEMA_FIELDS, f"UTM field '{field}' missing from SHARED_SCHEMA_FIELDS"
        for field in ATTRIBUTION_TRACKING_FIELDS:
            assert field in SHARED_SCHEMA_FIELDS, f"Attribution field '{field}' missing from SHARED_SCHEMA_FIELDS"
        for field in PATH_FIELDS:
            assert field in SHARED_SCHEMA_FIELDS, f"Path field '{field}' missing from SHARED_SCHEMA_FIELDS"

    def test_table_methods(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()
        stats_combined_table = WebStatsCombinedTable()
        bounces_combined_table = WebBouncesCombinedTable()

        assert stats_daily_table.to_printed_clickhouse(None) == "web_stats_daily"
        assert stats_daily_table.to_printed_hogql() == "web_stats_daily"

        assert bounces_daily_table.to_printed_clickhouse(None) == "web_bounces_daily"
        assert bounces_daily_table.to_printed_hogql() == "web_bounces_daily"

        assert stats_hourly_table.to_printed_clickhouse(None) == "web_stats_hourly"
        assert stats_hourly_table.to_printed_hogql() == "web_stats_hourly"

        assert bounces_hourly_table.to_printed_clickhouse(None) == "web_bounces_hourly"
        assert bounces_hourly_table.to_printed_hogql() == "web_bounces_hourly"

        assert stats_combined_table.to_printed_clickhouse(None) == "web_stats_combined"
        assert stats_combined_table.to_printed_hogql() == "web_stats_combined"

        assert bounces_combined_table.to_printed_clickhouse(None) == "web_bounces_combined"
        assert bounces_combined_table.to_printed_hogql() == "web_bounces_combined"

    def test_aggregation_fields_present(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()
        stats_combined_table = WebStatsCombinedTable()
        bounces_combined_table = WebBouncesCombinedTable()

        expected_agg_fields = ["persons_uniq_state", "sessions_uniq_state", "pageviews_count_state"]

        for field in expected_agg_fields:
            assert field in stats_daily_table.fields, f"Aggregation field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_daily_table.fields, f"Aggregation field '{field}' missing from WebBouncesDailyTable"
            assert field in stats_hourly_table.fields, f"Aggregation field '{field}' missing from WebStatsHourlyTable"
            assert (
                field in bounces_hourly_table.fields
            ), f"Aggregation field '{field}' missing from WebBouncesHourlyTable"
            assert (
                field in stats_combined_table.fields
            ), f"Aggregation field '{field}' missing from WebStatsCombinedTable"
            assert (
                field in bounces_combined_table.fields
            ), f"Aggregation field '{field}' missing from WebBouncesCombinedTable"

    def test_updated_at_field_present(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        assert "updated_at" in stats_daily_table.fields, "updated_at field missing from WebStatsDailyTable"
        assert "updated_at" in bounces_daily_table.fields, "updated_at field missing from WebBouncesDailyTable"
        assert "updated_at" in stats_hourly_table.fields, "updated_at field missing from WebStatsHourlyTable"
        assert "updated_at" in bounces_hourly_table.fields, "updated_at field missing from WebBouncesHourlyTable"

    def test_bucket_fields_present(self):
        stats_daily_table = WebStatsDailyTable()
        bounces_daily_table = WebBouncesDailyTable()
        stats_hourly_table = WebStatsHourlyTable()
        bounces_hourly_table = WebBouncesHourlyTable()

        # All tables should have period_bucket
        assert "period_bucket" in stats_daily_table.fields, "period_bucket field missing from WebStatsDailyTable"
        assert "period_bucket" in bounces_daily_table.fields, "period_bucket field missing from WebBouncesDailyTable"
        assert "period_bucket" in stats_hourly_table.fields, "period_bucket field missing from WebStatsHourlyTable"
        assert "period_bucket" in bounces_hourly_table.fields, "period_bucket field missing from WebBouncesHourlyTable"

        # No tables should have the old bucket fields
        assert "day_bucket" not in stats_daily_table.fields, "day_bucket field should not be in WebStatsDailyTable"
        assert "day_bucket" not in bounces_daily_table.fields, "day_bucket field should not be in WebBouncesDailyTable"
        assert "day_bucket" not in stats_hourly_table.fields, "day_bucket field should not be in WebStatsHourlyTable"
        assert (
            "day_bucket" not in bounces_hourly_table.fields
        ), "day_bucket field should not be in WebBouncesHourlyTable"

        assert "hour_bucket" not in stats_daily_table.fields, "hour_bucket field should not be in WebStatsDailyTable"
        assert (
            "hour_bucket" not in bounces_daily_table.fields
        ), "hour_bucket field should not be in WebBouncesDailyTable"
        assert "hour_bucket" not in stats_hourly_table.fields, "hour_bucket field should not be in WebStatsHourlyTable"
        assert (
            "hour_bucket" not in bounces_hourly_table.fields
        ), "hour_bucket field should not be in WebBouncesHourlyTable"
