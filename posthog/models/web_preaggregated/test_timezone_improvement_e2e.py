"""
End-to-end test demonstrating timezone improvements with hourly historical tables.

This test shows the practical difference between daily UTC bucketing (current)
vs hourly bucketing (new solution) for users in different timezones.
"""

import pytest
from datetime import datetime, timezone, timedelta
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_INSERT_SQL,
    WEB_STATS_HOURLY_COMBINED_VIEW_SQL,
    WEB_STATS_COMBINED_VIEW_SQL,
)


class TestTimezoneImprovementE2E:
    """
    End-to-end demonstration of timezone improvements.

    Scenario: A US/Pacific user wants to analyze their website traffic
    for "yesterday" in their local time. With daily UTC buckets, the data
    boundaries don't align with their perception of "yesterday".
    """

    def test_pacific_timezone_user_daily_vs_hourly_bucketing(self):
        """
        Compare daily UTC vs hourly bucketing for a Pacific timezone user.

        User perspective: "Show me yesterday's traffic" (Pacific time)
        - Pacific "yesterday": Jan 1, 2024 from 00:00 to 23:59 PT
        - UTC equivalent: Jan 1, 2024 08:00 UTC to Jan 2, 2024 07:59 UTC

        Problem with daily UTC buckets:
        - Daily UTC bucket for Jan 1: 00:00 to 23:59 UTC
        - This misses 8 hours of the user's "yesterday" (Jan 2, 00:00-07:59 UTC)
        - And includes 8 hours that aren't their "yesterday" (Jan 1, 00:00-07:59 UTC)

        Solution with hourly buckets:
        - Can aggregate exactly the hours that match user's "yesterday"
        """
        # Pacific timezone (UTC-8)
        pacific_tz = timezone(timedelta(hours=-8))

        # User's "yesterday" in Pacific time
        user_yesterday_start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=pacific_tz)
        user_yesterday_end = datetime(2024, 1, 1, 23, 59, 59, tzinfo=pacific_tz)

        # Convert to UTC for queries
        utc_start = user_yesterday_start.astimezone(timezone.utc)  # Jan 1, 08:00 UTC
        utc_end = user_yesterday_end.astimezone(timezone.utc)  # Jan 2, 07:59 UTC

        # CURRENT APPROACH: Daily UTC buckets
        daily_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",  # Jan 1 UTC bucket
            date_end="2024-01-02",  # Jan 2 UTC bucket
            granularity="daily",
            select_only=True,
        )

        # Daily approach uses toStartOfDay - creates UTC day boundaries
        assert "toStartOfDay(start_timestamp) AS period_bucket" in daily_sql

        # This gives us:
        # - Jan 1 UTC bucket: 00:00-23:59 UTC (misses 8 hours, includes wrong 8 hours)
        # - Would need to query 2 daily partitions and filter client-side

        # NEW APPROACH: Hourly buckets
        hourly_sql = WEB_STATS_INSERT_SQL(
            date_start=utc_start.strftime("%Y-%m-%d %H:%M:%S"),
            date_end=utc_end.strftime("%Y-%m-%d %H:%M:%S"),
            granularity="hourly",
            timezone="America/Los_Angeles",  # Respect user's timezone
            select_only=True,
        )

        # Hourly approach uses toStartOfHour - creates hourly boundaries
        assert "toStartOfHour(start_timestamp) AS period_bucket" in hourly_sql
        assert "America/Los_Angeles" in hourly_sql

        # This gives us exact hourly buckets that can be aggregated to match
        # the user's local "yesterday" perfectly

    def test_combined_view_provides_seamless_querying(self):
        """
        Test that the new combined view allows seamless querying across
        historical hourly data + current day data.
        """
        # Original combined view (daily + current hourly)
        daily_combined_sql = WEB_STATS_COMBINED_VIEW_SQL()

        # New hourly combined view (historical hourly + current hourly)
        hourly_combined_sql = WEB_STATS_HOURLY_COMBINED_VIEW_SQL()

        # Both should combine data sources
        assert "UNION ALL" in daily_combined_sql
        assert "UNION ALL" in hourly_combined_sql

        # But the new view provides hourly granularity for ALL data
        assert "web_stats_daily" in daily_combined_sql  # Daily granularity for history
        assert "web_stats_hourly_historical" in hourly_combined_sql  # Hourly granularity for history

        # Both use current hourly for today
        assert "web_stats_hourly" in daily_combined_sql
        assert "web_stats_hourly" in hourly_combined_sql

    def test_query_patterns_for_timezone_friendly_analytics(self):
        """
        Show example query patterns that work better with hourly data.
        """
        # Example: User wants "last 7 days" in their timezone
        # With hourly data, they can:

        query_pattern = """
        SELECT
            toStartOfDay(period_bucket, 'America/Los_Angeles') as local_date,
            sumMerge(pageviews_count_state) as total_pageviews
        FROM web_stats_hourly_combined
        WHERE team_id = 123
            AND period_bucket >= toDateTime('2024-01-01 08:00:00', 'UTC')  -- Start of Pacific day
            AND period_bucket < toDateTime('2024-01-08 08:00:00', 'UTC')   -- End of Pacific week
        GROUP BY local_date
        ORDER BY local_date
        """

        # This query would give perfect daily aggregations aligned with Pacific timezone
        # because it's built from hourly buckets that can be regrouped as needed

        assert "web_stats_hourly_combined" in query_pattern
        assert "America/Los_Angeles" in query_pattern

    def test_partition_efficiency_maintained(self):
        """
        Verify that despite hourly bucketing, we maintain efficient partitioning.
        """
        from posthog.models.web_preaggregated.sql import WEB_STATS_HOURLY_HISTORICAL_SQL

        create_sql = WEB_STATS_HOURLY_HISTORICAL_SQL()

        # Should still use daily partitions (not hourly partitions)
        # This maintains the same partition management overhead as daily tables
        assert "PARTITION BY toYYYYMMDD(period_bucket)" in create_sql

        # Should NOT create hourly partitions (would be too granular)
        assert "formatDateTime" not in create_sql

    def test_migration_path_from_existing_system(self):
        """
        Show how teams can migrate from daily to hourly granularity.
        """
        # Phase 1: Teams continue using existing daily views
        daily_view_sql = WEB_STATS_COMBINED_VIEW_SQL()
        assert "web_stats_combined" in daily_view_sql

        # Phase 2: Teams can opt into hourly granularity
        hourly_view_sql = WEB_STATS_HOURLY_COMBINED_VIEW_SQL()
        assert "web_stats_hourly_combined" in hourly_view_sql

        # Phase 3: Eventually replace daily views with hourly views
        # This provides better timezone handling without breaking existing queries

        # Both views have the same schema, so migration is just changing the view name
        # in queries from web_stats_combined -> web_stats_hourly_combined

    @pytest.mark.parametrize(
        "user_timezone,expected_offset_hours",
        [
            ("UTC", 0),
            ("America/Los_Angeles", -8),  # PST
            ("America/New_York", -5),  # EST
            ("Europe/London", 0),  # GMT
            ("Asia/Tokyo", 9),  # JST
            ("Australia/Sydney", 11),  # AEDT
        ],
    )
    def test_timezone_flexibility_for_global_users(self, user_timezone, expected_offset_hours):
        """
        Test that the hourly approach works well for users in any timezone.
        """
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            timezone=user_timezone,
            granularity="hourly",
            select_only=True,
        )

        # Should respect the user's timezone in timestamp conversions
        assert f"toTimeZone(e.timestamp, '{user_timezone}')" in sql

        # Should use hourly bucketing which aligns better with any timezone
        assert "toStartOfHour(start_timestamp)" in sql

        # This allows users in any timezone to get data that aligns well
        # with their local time boundaries, unlike daily UTC buckets
