import pytest
import time_machine
from posthog.test.base import _create_event, _create_person

from parameterized import parameterized

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import (
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
    get_all_filters,
    get_date_filters,
    get_team_filters,
    get_web_bounces_insert_columns,
    get_web_stats_insert_columns,
)
from posthog.models.web_preaggregated.team_selection import WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL

from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)


class TestWebPreaggregatedInserts(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with time_machine.travel("2024-01-01T09:00:00Z", tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["user_0"])

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_0",
                timestamp="2024-01-01T10:00:00Z",
                properties={
                    "$session_id": str(uuid7("2024-01-01")),
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "New York",
                    "$geoip_subdivision_1_code": "NY",
                    "utm_source": "google",
                    "utm_medium": "cpc",
                    "utm_campaign": "summer_sale",
                    "$referring_domain": "google.com",
                },
            )

    @parameterized.expand([("explicit_team_ids", True), ("team_selection_table", False)])
    def test_insert_queries_aggregate_the_selected_team(self, _name: str, pass_team_ids: bool):
        if pass_team_ids:
            team_ids: list[int] | None = [self.team.pk]
        else:
            team_ids = None
            sync_execute(WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL([self.team.pk]))

        for table_name, sql_builder in [
            ("web_pre_aggregated_stats", WEB_STATS_INSERT_SQL),
            ("web_pre_aggregated_bounces", WEB_BOUNCES_INSERT_SQL),
        ]:
            sync_execute(
                sql_builder(date_start="2024-01-01", date_end="2024-01-02", team_ids=team_ids, table_name=table_name)
            )
            [(row_count,)] = sync_execute(
                f"SELECT count() FROM {table_name} WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
            )
            assert row_count > 0, table_name

    def test_insert_queries_contain_all_columns_for_stats(self):
        stats_insert = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[self.team.pk],
            table_name="web_pre_aggregated_stats",
        )

        expected_stats_columns = get_web_stats_insert_columns()
        for column in expected_stats_columns:
            assert f"\n    {column}" in stats_insert

        # Verify it has explicit column list format
        assert "INSERT INTO web_pre_aggregated_stats\n(" in stats_insert
        assert ")\n\n    SELECT" in stats_insert

    def test_insert_queries_contain_all_columns_for_bounces(self):
        # Test WEB_BOUNCES_INSERT_SQL contains correct columns
        bounces_insert = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[self.team.pk],
            table_name="web_pre_aggregated_bounces",
        )

        expected_bounces_columns = get_web_bounces_insert_columns()
        for column in expected_bounces_columns:
            assert f"\n    {column}" in bounces_insert

        # Verify it has explicit column list format
        assert "INSERT INTO web_pre_aggregated_bounces\n(" in bounces_insert
        assert ")\n\n    SELECT" in bounces_insert


class TestCentralizedFilters:
    """Test the centralized filter functionality introduced for UTC boundary fixes."""

    def test_get_team_filters_with_team_ids(self):
        team_ids = [123, 456, 789]
        filters = get_team_filters(team_ids)

        assert "raw_sessions.team_id IN(123, 456, 789)" == filters["raw_sessions"]
        assert "person_distinct_id_overrides.team_id IN(123, 456, 789)" == filters["person_distinct_id_overrides"]
        assert "e.team_id IN(123, 456, 789)" == filters["events"]

    @pytest.mark.parametrize("team_ids", [None, []])
    def test_get_team_filters_without_team_ids_uses_team_selection_table(self, team_ids):
        filters = get_team_filters(team_ids)

        for key, column in [
            ("raw_sessions", "raw_sessions.team_id"),
            ("person_distinct_id_overrides", "person_distinct_id_overrides.team_id"),
            ("events", "e.team_id"),
        ]:
            assert filters[key].startswith(f"{column} GLOBAL IN (")
            assert "web_pre_aggregated_teams" in filters[key]
            assert "dictHas" not in filters[key]

    @pytest.mark.parametrize(
        "granularity,expected_session_start,expected_event_start",
        [
            ("daily", "minus(toDateTime('2024-01-01', 'UTC'), toIntervalHour(24))", "toDateTime('2024-01-01', 'UTC')"),
            (
                "hourly",
                "minus(toDateTime('2024-01-01', 'UTC'), toIntervalHour(25))",
                "minus(toDateTime('2024-01-01', 'UTC'), toIntervalHour(1))",
            ),
        ],
    )
    def test_get_date_filters_granularity_differences(self, granularity, expected_session_start, expected_event_start):
        filters = get_date_filters("2024-01-01", "2024-01-02", "UTC", granularity)

        assert filters["session_start_filter"] == expected_session_start
        assert filters["event_start_filter"] == expected_event_start
        assert filters["target_period_start"] == "toDateTime('2024-01-01', 'UTC')"
        assert filters["target_period_end"] == "toDateTime('2024-01-02', 'UTC')"

    def test_get_date_filters_contains_all_required_keys(self):
        filters = get_date_filters("2024-01-01", "2024-01-02", "UTC", "daily")

        required_keys = [
            "session_start_filter",
            "session_end_filter",
            "event_start_filter",
            "event_end_filter",
            "target_period_start",
            "target_period_end",
        ]
        for key in required_keys:
            assert key in filters

    @pytest.mark.parametrize(
        "granularity,expected_time_bucket",
        [
            ("daily", "toStartOfDay"),
            ("hourly", "toStartOfHour"),
        ],
    )
    def test_get_all_filters_time_bucket_function(self, granularity, expected_time_bucket):
        filters = get_all_filters("2024-01-01", "2024-01-02", "UTC", [123], granularity, "")

        assert filters["time_bucket_func"] == expected_time_bucket

    def test_get_all_filters_settings_clause_formatting(self):
        # Test with settings
        filters_with_settings = get_all_filters("2024-01-01", "2024-01-02", "UTC", None, "daily", "max_threads=8")
        assert filters_with_settings["settings_clause"] == "SETTINGS max_threads=8"

        # Test without settings
        filters_without_settings = get_all_filters("2024-01-01", "2024-01-02", "UTC", None, "daily", "")
        assert filters_without_settings["settings_clause"] == ""

    def test_get_all_filters_contains_all_required_parameters(self):
        filters = get_all_filters("2024-01-01", "2024-01-02", "America/New_York", [123, 456], "hourly", "max_threads=4")

        # Basic parameters
        assert filters["date_start"] == "2024-01-01"
        assert filters["date_end"] == "2024-01-02"
        assert filters["timezone"] == "America/New_York"

        # Team filters
        assert "team_id IN(123, 456)" in filters["team_filter"]
        assert "team_id IN(123, 456)" in filters["person_team_filter"]
        assert "team_id IN(123, 456)" in filters["events_team_filter"]

        # Date filters (from get_date_filters)
        assert "session_start_filter" in filters
        assert "target_period_start" in filters

        # Settings and time bucket
        assert filters["settings_clause"] == "SETTINGS max_threads=4"
        assert filters["time_bucket_func"] == "toStartOfHour"

    def test_get_all_filters_hourly_extended_session_range(self):
        """Test that hourly granularity extends session range by 25 hours for UTC boundary fix."""
        filters = get_all_filters("2024-01-01", "2024-01-02", "UTC", None, "hourly", "")

        # Should extend 25 hours before start for sessions
        assert "toIntervalHour(25)" in filters["session_start_filter"]
        assert "minus(toDateTime('2024-01-01', 'UTC')" in filters["session_start_filter"]

        # Should extend 1 hour after end for sessions
        assert "plus(toDateTime('2024-01-02', 'UTC'), toIntervalHour(1))" in filters["session_end_filter"]

    def test_sql_generation_uses_centralized_filters(self):
        """Test that the SQL functions use centralized filters correctly."""
        stats_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[123],
            timezone="UTC",
            settings="max_threads=4",
            granularity="hourly",
            select_only=True,
        )

        # Verify key elements from centralized filters are present
        assert "toStartOfHour" in stats_sql  # time_bucket_func
        assert "team_id IN(123)" in stats_sql  # team_filter
        assert "SETTINGS max_threads=4" in stats_sql  # settings_clause
        assert "toIntervalHour(25)" in stats_sql  # extended session range
        assert "period_bucket >= toDateTime('2024-01-01', 'UTC')" in stats_sql  # outer filter
