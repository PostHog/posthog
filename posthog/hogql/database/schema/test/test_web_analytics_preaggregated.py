from parameterized import parameterized
from posthog.hogql.database.models import Table
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
    PATH_FIELDS,
    WEB_STATS_SPECIFIC_FIELDS,
    WEB_BOUNCES_SPECIFIC_FIELDS,
)


class TestWebAnalyticsPreAggregatedSchema:
    DEVICE_BROWSER_FIELD_NAMES = ["browser", "os", "viewport_width", "viewport_height"]
    GEOIP_FIELD_NAMES = ["country_code", "city_name", "region_code", "region_name"]
    UTM_FIELD_NAMES = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "referring_domain"]
    PATH_FIELD_NAMES = ["entry_pathname", "end_pathname"]
    AGGREGATION_FIELD_NAMES = ["persons_uniq_state", "sessions_uniq_state", "pageviews_count_state"]

    TABLE_CONFIGS = [
        ("WebStatsDailyTable", WebStatsDailyTable, "web_stats_daily"),
        ("WebBouncesDailyTable", WebBouncesDailyTable, "web_bounces_daily"),
        ("WebStatsHourlyTable", WebStatsHourlyTable, "web_stats_hourly"),
        ("WebBouncesHourlyTable", WebBouncesHourlyTable, "web_bounces_hourly"),
        ("WebStatsCombinedTable", WebStatsCombinedTable, "web_stats_combined"),
        ("WebBouncesCombinedTable", WebBouncesCombinedTable, "web_bounces_combined"),
    ]

    @property
    def all_tables(self) -> dict[str, Table]:
        if not hasattr(self, "_tables"):
            self._tables = {name: cls() for name, cls, _ in self.TABLE_CONFIGS}
        return self._tables

    @property
    def stats_tables(self) -> dict[str, Table]:
        return {k: v for k, v in self.all_tables.items() if "Stats" in k}

    @property
    def bounces_tables(self) -> dict[str, Table]:
        return {k: v for k, v in self.all_tables.items() if "Bounces" in k}

    @property
    def non_combined_tables(self) -> dict[str, Table]:
        return {k: v for k, v in self.all_tables.items() if "Combined" not in k}

    def _assert_fields_in_tables(self, field_names: list[str], tables: dict[str, Table], should_contain: bool = True):
        for field_name in field_names:
            for _, table_instance in tables.items():
                if should_contain:
                    assert field_name in table_instance.fields
                else:
                    assert field_name not in table_instance.fields

    def _assert_field_groups_in_tables(self, field_groups: dict[str, list[str]], tables: dict[str, Table]):
        for _, field_names in field_groups.items():
            self._assert_fields_in_tables(field_names, tables)

    def test_shared_fields_present_in_all_tables(self):
        shared_field_names = list(SHARED_SCHEMA_FIELDS.keys())
        self._assert_fields_in_tables(shared_field_names, self.all_tables)

    @parameterized.expand(
        [
            ("device_browser", "DEVICE_BROWSER_FIELD_NAMES"),
            ("geoip", "GEOIP_FIELD_NAMES"),
            ("utm", "UTM_FIELD_NAMES"),
            ("path", "PATH_FIELD_NAMES"),
            ("aggregation", "AGGREGATION_FIELD_NAMES"),
        ]
    )
    def test_field_groups_present_in_all_tables(self, group_name: str, field_attr_name: str):
        field_names = getattr(self, field_attr_name)
        self._assert_fields_in_tables(field_names, self.all_tables)

    def test_table_specific_fields_separation(self):
        stats_field_names = list(WEB_STATS_SPECIFIC_FIELDS.keys())
        self._assert_fields_in_tables(stats_field_names, self.stats_tables, should_contain=True)
        self._assert_fields_in_tables(stats_field_names, self.bounces_tables, should_contain=False)

        bounces_field_names = list(WEB_BOUNCES_SPECIFIC_FIELDS.keys())
        self._assert_fields_in_tables(bounces_field_names, self.bounces_tables, should_contain=True)
        self._assert_fields_in_tables(bounces_field_names, self.stats_tables, should_contain=False)

    def test_specific_field_presence_rules(self):
        # pathname should only be in stats tables
        self._assert_fields_in_tables(["pathname"], self.stats_tables, should_contain=True)
        self._assert_fields_in_tables(["pathname"], self.bounces_tables, should_contain=False)

        bounce_specific_agg_fields = ["bounces_count_state", "total_session_duration_state"]
        self._assert_fields_in_tables(bounce_specific_agg_fields, self.bounces_tables, should_contain=True)
        self._assert_fields_in_tables(bounce_specific_agg_fields, self.stats_tables, should_contain=False)

    def test_shared_schema_fields_composition(self):
        expected_field_count = sum(
            [
                len(DEVICE_BROWSER_FIELDS),
                len(GEOIP_FIELDS),
                len(UTM_FIELDS),
                len(PATH_FIELDS),
            ]
        )

        assert (
            len(SHARED_SCHEMA_FIELDS) == expected_field_count
        ), f"SHARED_SCHEMA_FIELDS has {len(SHARED_SCHEMA_FIELDS)} fields, expected {expected_field_count}"

        field_groups = {
            "device_browser": list(DEVICE_BROWSER_FIELDS.keys()),
            "geoip": list(GEOIP_FIELDS.keys()),
            "utm": list(UTM_FIELDS.keys()),
            "path": list(PATH_FIELDS.keys()),
        }

        for group_name, field_names in field_groups.items():
            for field_name in field_names:
                assert (
                    field_name in SHARED_SCHEMA_FIELDS
                ), f"{group_name.title()} field '{field_name}' missing from SHARED_SCHEMA_FIELDS"
