from posthog.hogql.database.schema.web_analytics_preaggregated import (
    WebStatsDailyTable,
    WebBouncesDailyTable,
    SHARED_SCHEMA_FIELDS,
    DEVICE_BROWSER_FIELDS,
    GEOIP_FIELDS,
    UTM_FIELDS,
    ATTRIBUTION_TRACKING_FIELDS,
    PATH_FIELDS,
    WEB_STATS_DAILY_SPECIFIC_FIELDS,
    WEB_BOUNCES_DAILY_SPECIFIC_FIELDS,
)


class TestWebAnalyticsPreAggregatedSchema:
    def test_shared_fields_present_in_both_tables(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        for field_name in SHARED_SCHEMA_FIELDS.keys():
            assert field_name in stats_table.fields, f"Shared field '{field_name}' missing from WebStatsDailyTable"
            assert field_name in bounces_table.fields, f"Shared field '{field_name}' missing from WebBouncesDailyTable"

    def test_table_specific_fields(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        # Stats table specific fields
        for field_name in WEB_STATS_DAILY_SPECIFIC_FIELDS.keys():
            assert (
                field_name in stats_table.fields
            ), f"Stats-specific field '{field_name}' missing from WebStatsDailyTable"

        # Bounces table specific fields
        for field_name in WEB_BOUNCES_DAILY_SPECIFIC_FIELDS.keys():
            assert (
                field_name in bounces_table.fields
            ), f"Bounces-specific field '{field_name}' missing from WebBouncesDailyTable"

        # Verify pathname is only in stats table
        assert "pathname" in stats_table.fields
        assert "pathname" not in bounces_table.fields

        # Verify bounce-specific fields are only in bounces table
        assert "bounces_count_state" not in stats_table.fields
        assert "total_session_duration_state" not in stats_table.fields
        assert "bounces_count_state" in bounces_table.fields
        assert "total_session_duration_state" in bounces_table.fields

    def test_device_browser_fields(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        expected_fields = ["browser", "browser_version", "os", "os_version", "viewport_width", "viewport_height"]

        for field in expected_fields:
            assert field in stats_table.fields, f"Device/browser field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_table.fields, f"Device/browser field '{field}' missing from WebBouncesDailyTable"

    def test_geoip_fields(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        expected_fields = ["country_code", "country_name", "city_name", "region_code", "region_name", "time_zone"]

        for field in expected_fields:
            assert field in stats_table.fields, f"GeoIP field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_table.fields, f"GeoIP field '{field}' missing from WebBouncesDailyTable"

    def test_attribution_tracking_fields(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

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
            assert field in stats_table.fields, f"Attribution field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_table.fields, f"Attribution field '{field}' missing from WebBouncesDailyTable"

    def test_utm_fields(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        expected_fields = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "referring_domain"]

        for field in expected_fields:
            assert field in stats_table.fields, f"UTM field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_table.fields, f"UTM field '{field}' missing from WebBouncesDailyTable"

    def test_path_fields(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        expected_fields = ["entry_pathname", "end_pathname"]

        for field in expected_fields:
            assert field in stats_table.fields, f"Path field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_table.fields, f"Path field '{field}' missing from WebBouncesDailyTable"

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
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        assert stats_table.to_printed_clickhouse(None) == "web_stats_daily FINAL"
        assert stats_table.to_printed_hogql() == "web_stats_daily"

        assert bounces_table.to_printed_clickhouse(None) == "web_bounces_daily FINAL"
        assert bounces_table.to_printed_hogql() == "web_bounces_daily"

    def test_aggregation_fields_present(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        # Test that the new aggregation fields are present
        expected_agg_fields = ["persons_uniq_state", "sessions_uniq_state", "pageviews_count_state"]

        for field in expected_agg_fields:
            assert field in stats_table.fields, f"Aggregation field '{field}' missing from WebStatsDailyTable"
            assert field in bounces_table.fields, f"Aggregation field '{field}' missing from WebBouncesDailyTable"

    def test_updated_at_field_present(self):
        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        assert "updated_at" in stats_table.fields, "updated_at field missing from WebStatsDailyTable"
        assert "updated_at" in bounces_table.fields, "updated_at field missing from WebBouncesDailyTable"
