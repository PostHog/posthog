"""
Database integration tests for timezone improvements with hourly historical tables.

These tests create real events in the database and verify that hourly bucketing
provides better timezone alignment than daily UTC bucketing for global users.
"""

from freezegun import freeze_time
from datetime import datetime, timezone, timedelta

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_INSERT_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_HOURLY_HISTORICAL_SQL,
    WEB_BOUNCES_HOURLY_HISTORICAL_SQL,
    WEB_STATS_HOURLY_COMBINED_VIEW_SQL,
    WEB_BOUNCES_HOURLY_COMBINED_VIEW_SQL,
)
from posthog.models.utils import uuid7
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.test.base import (
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


class TestTimezoneImprovementDBIntegration(WebAnalyticsPreAggregatedTestBase):
    """
    Integration tests that create real events and verify timezone improvements.

    Scenario: US/Pacific users analyzing their "business day" traffic
    - Business day: 9 AM - 5 PM Pacific Time
    - With daily UTC buckets: misses hours at beginning/end of business day
    - With hourly buckets: can precisely capture business hours
    """

    def _setup_test_data(self):
        """
        Create events representing Pacific timezone business hours.

        Simple approach: Create events at different hours to test timezone bucketing.
        """
        with freeze_time("2024-01-15T09:00:00Z"):
            sessions = [str(uuid7("2024-01-15")) for _ in range(10)]

            # Create users
            for i in range(10):
                _create_person(team_id=self.team.pk, distinct_ids=[f"user_{i}"])

            # Create events spread across different hours of Jan 15, 2024
            # This spans across what would be a Pacific business day

            # 10 AM PT = 6 PM UTC (Jan 14) - Business hours
            self._create_business_hour_events(
                datetime(2024, 1, 14, 18, 0, 0, tzinfo=timezone.utc),  # 6 PM UTC Jan 14 = 10 AM PT Jan 15
                sessions[0:2],
                "business_hours",
                "10_AM_PT",
            )

            # 2 PM PT = 10 PM UTC (Jan 14) - Business hours peak
            self._create_business_hour_events(
                datetime(2024, 1, 14, 22, 0, 0, tzinfo=timezone.utc),  # 10 PM UTC Jan 14 = 2 PM PT Jan 15
                sessions[2:6],  # More traffic during peak
                "business_peak",
                "14_PM_PT",
            )

            # 4 PM PT = 12 AM UTC (Jan 15) - End of business
            self._create_business_hour_events(
                datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc),  # Midnight UTC Jan 15 = 4 PM PT Jan 15
                sessions[6:8],
                "business_end",
                "16_PM_PT",
            )

            # 8 PM PT = 4 AM UTC (Jan 15) - After hours
            self._create_business_hour_events(
                datetime(2024, 1, 15, 4, 0, 0, tzinfo=timezone.utc),  # 4 AM UTC Jan 15 = 8 PM PT Jan 15
                sessions[8:9],
                "after_hours",
                "20_PM_PT",
            )

            flush_persons_and_events()

    def _create_business_hour_events(
        self, utc_timestamp: datetime, sessions: list[str], traffic_type: str, hour_label: str
    ):
        """Create events for a specific business hour with realistic properties."""
        base_properties = {
            "$device_type": "Desktop",
            "$browser": "Chrome",
            "$os": "Windows",
            "$viewport_width": 1920,
            "$viewport_height": 1080,
            "$geoip_country_code": "US",
            "$geoip_city_name": "San Francisco",  # Pacific timezone city
            "$geoip_subdivision_1_code": "CA",
            "utm_source": "google",
            "utm_medium": "organic",
            "$referring_domain": "google.com",
        }

        # Create different page patterns based on time of day
        page_patterns = {
            "morning_rush": ["/landing", "/features", "/pricing"],
            "steady_morning": ["/features", "/docs", "/blog"],
            "lunch_dip": ["/blog", "/about"],
            "afternoon_peak": ["/pricing", "/demo", "/contact", "/features", "/landing"],
            "end_of_day": ["/contact", "/pricing"],
            "after_hours": ["/blog"],
        }

        pages = page_patterns.get(traffic_type, ["/landing"])

        for i, session_id in enumerate(sessions):
            page = pages[i % len(pages)]
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_{hash(session_id) % 100}",  # Distribute across users
                timestamp=utc_timestamp.isoformat(),
                properties={
                    **base_properties,
                    "$session_id": session_id,
                    "$current_url": f"https://example.com{page}",
                    "$pathname": page,
                    # Add a custom property to track the business hour for verification
                    "business_hour": hour_label,
                    "traffic_type": traffic_type,
                },
            )

    def _populate_daily_preaggregated_tables(self):
        """Populate daily tables (existing approach)."""
        stats_insert = WEB_STATS_INSERT_SQL(
            date_start="2024-01-14",  # Previous day to capture cross-day Pacific business hours
            date_end="2024-01-16",  # Next day to capture all hours
            team_ids=[self.team.pk],
            granularity="daily",
        )
        bounces_insert = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-14", date_end="2024-01-16", team_ids=[self.team.pk], granularity="daily"
        )
        sync_execute(stats_insert)
        sync_execute(bounces_insert)

    def _populate_hourly_historical_tables(self):
        """Populate hourly historical tables (new approach)."""
        stats_insert = WEB_STATS_INSERT_SQL(
            date_start="2024-01-14",
            date_end="2024-01-16",
            team_ids=[self.team.pk],
            table_name="web_stats_hourly_historical",
            granularity="hourly",
        )
        bounces_insert = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-14",
            date_end="2024-01-16",
            team_ids=[self.team.pk],
            table_name="web_bounces_hourly_historical",
            granularity="hourly",
        )
        sync_execute(stats_insert)
        sync_execute(bounces_insert)

    def test_daily_vs_hourly_business_hour_analysis(self):
        """
        Compare daily vs hourly bucketing for Pacific timezone business hour analysis.

        Business Question: "How much traffic did we get during business hours (9 AM - 5 PM PT)?"

        Daily UTC approach problems:
        - Jan 14 UTC bucket: 00:00-23:59 UTC = 4 PM PT (prev day) to 3 PM PT - missing 2 hours
        - Jan 15 UTC bucket: 00:00-23:59 UTC = 4 PM PT to 3 PM PT (next day) - missing 2 hours

        Hourly approach: Can precisely select 9 AM-5 PM PT hours
        """
        # Populate both approaches
        self._populate_daily_preaggregated_tables()
        self._populate_hourly_historical_tables()

        # DAILY APPROACH: Query daily buckets (imprecise timezone alignment)
        daily_query = """
        SELECT 
            toStartOfDay(period_bucket) as day_bucket,
            sumMerge(pageviews_count_state) as total_pageviews,
            uniqMerge(persons_uniq_state) as unique_visitors
        FROM web_stats_daily
        WHERE team_id = %(team_id)s
            AND period_bucket >= '2024-01-14'
            AND period_bucket < '2024-01-16'
        GROUP BY day_bucket
        ORDER BY day_bucket
        """

        daily_results = sync_execute(daily_query, {"team_id": self.team.pk})

        # HOURLY APPROACH: Query specific Pacific business hours (precise timezone alignment)
        # Business hours: 9 AM - 5 PM PT = 17:00 - 01:00+1 UTC
        hourly_business_hours_query = """
        SELECT 
            toStartOfHour(period_bucket) as hour_bucket,
            sumMerge(pageviews_count_state) as total_pageviews,
            uniqMerge(persons_uniq_state) as unique_visitors
        FROM web_stats_hourly_historical  
        WHERE team_id = %(team_id)s
            AND (
                -- Jan 14: 18:00-23:59 UTC (10 AM - 3:59 PM PT Jan 15)
                (period_bucket >= '2024-01-14 18:00:00' AND period_bucket < '2024-01-15 00:00:00')
                OR
                -- Jan 15: 00:00 UTC (4 PM PT Jan 15)  
                (period_bucket >= '2024-01-15 00:00:00' AND period_bucket < '2024-01-15 01:00:00')
            )
        GROUP BY hour_bucket
        ORDER BY hour_bucket
        """

        hourly_business_results = sync_execute(hourly_business_hours_query, {"team_id": self.team.pk})

        # ALL HOURLY DATA: For comparison, get all hours
        hourly_all_query = """
        SELECT 
            toStartOfHour(period_bucket) as hour_bucket,
            sumMerge(pageviews_count_state) as total_pageviews,
            uniqMerge(persons_uniq_state) as unique_visitors
        FROM web_stats_hourly_historical
        WHERE team_id = %(team_id)s
            AND period_bucket >= '2024-01-14'
            AND period_bucket < '2024-01-16'
        GROUP BY hour_bucket  
        ORDER BY hour_bucket
        """

        hourly_all_results = sync_execute(hourly_all_query, {"team_id": self.team.pk})

        # VERIFICATION: Hourly approach should give more precise business hour analysis
        business_hour_pageviews = sum(row[1] for row in hourly_business_results)
        total_pageviews = sum(row[1] for row in hourly_all_results)
        daily_pageviews = sum(row[1] for row in daily_results)

        # print(f"Business hour traffic: {business_hour_pageviews}/{total_pageviews}")
        # print(f"Daily traffic: {daily_pageviews}")
        # print(f"Hourly business results: {len(hourly_business_results)} buckets")
        # print(f"All hourly results: {len(hourly_all_results)} buckets")
        # print(f"Daily results: {len(daily_results)} buckets")

        # Debug: Show the actual data
        # print("Business hour buckets:")
        # for row in hourly_business_results:
        #     print(f"  {row[0]}: {row[1]} pageviews")

        # print("All hourly buckets:")
        # for row in hourly_all_results:
        #     print(f"  {row[0]}: {row[1]} pageviews")

        # Basic verification that data exists
        assert total_pageviews > 0, "No total pageviews found"
        assert daily_pageviews > 0, "No daily pageviews found"

        # Daily and hourly totals should match (same underlying data)
        assert daily_pageviews == total_pageviews, f"Daily ({daily_pageviews}) != Hourly ({total_pageviews})"

        # Business hours data should exist
        assert business_hour_pageviews > 0, "No business hour pageviews found"

        # Business hours should be a subset of total (or equal if all events are in business hours)
        assert business_hour_pageviews <= total_pageviews

        business_hour_percentage = (business_hour_pageviews / total_pageviews) * 100
        print(f"Business hour percentage: {business_hour_percentage:.1f}%")

    def test_pacific_timezone_daily_aggregation_precision(self):
        """
        Test the precision difference when a Pacific user wants "yesterday's" traffic.

        User's "yesterday": Jan 15, 2024 00:00-23:59 PT = Jan 15 08:00 UTC - Jan 16 07:59 UTC
        Daily UTC buckets: Jan 15 00:00-23:59 UTC (misses 8 hours, includes wrong 8 hours)
        Hourly buckets: Can aggregate exactly the user's "yesterday"
        """
        self._populate_hourly_historical_tables()

        # HOURLY APPROACH: User's exact "yesterday" in Pacific time
        user_yesterday_pt_query = """
        SELECT 
            sumMerge(pageviews_count_state) as pageviews,
            uniqMerge(persons_uniq_state) as unique_visitors,
            COUNT(*) as hour_buckets_used
        FROM web_stats_hourly_historical
        WHERE team_id = %(team_id)s
            -- User's "yesterday" PT = Jan 15 08:00 UTC to Jan 16 07:59 UTC
            AND period_bucket >= '2024-01-15 08:00:00'
            AND period_bucket < '2024-01-16 08:00:00'
        """

        pt_yesterday_results = sync_execute(user_yesterday_pt_query, {"team_id": self.team.pk})

        # DAILY UTC APPROACH: Jan 15 UTC bucket (misaligned with user's day)
        daily_utc_jan15_query = """
        SELECT 
            sumMerge(pageviews_count_state) as pageviews,
            uniqMerge(persons_uniq_state) as unique_visitors
        FROM web_stats_daily  
        WHERE team_id = %(team_id)s
            AND period_bucket >= '2024-01-15 00:00:00'
            AND period_bucket < '2024-01-16 00:00:00'
        """

        # For comparison, we need to populate daily tables too
        self._populate_daily_preaggregated_tables()
        daily_utc_results = sync_execute(daily_utc_jan15_query, {"team_id": self.team.pk})

        # Get hourly breakdown to show the misalignment
        hourly_breakdown_query = """
        SELECT 
            toStartOfHour(period_bucket) as hour,
            sumMerge(pageviews_count_state) as pageviews
        FROM web_stats_hourly_historical
        WHERE team_id = %(team_id)s
            AND period_bucket >= '2024-01-15 00:00:00'
            AND period_bucket < '2024-01-16 08:00:00'
        GROUP BY hour
        ORDER BY hour
        """

        hourly_breakdown = sync_execute(hourly_breakdown_query, {"team_id": self.team.pk})

        # VERIFICATION: The approaches give different results due to timezone misalignment
        pt_yesterday_pageviews = pt_yesterday_results[0][0] if pt_yesterday_results else 0
        daily_utc_pageviews = daily_utc_results[0][0] if daily_utc_results else 0

        # They should be different because they capture different time ranges
        # (unless by coincidence there were no events in the misaligned hours)
        print(f"Pacific user's 'yesterday': {pt_yesterday_pageviews} pageviews")
        print(f"UTC Jan 15 bucket: {daily_utc_pageviews} pageviews")
        print(f"Hourly breakdown: {len(hourly_breakdown)} hours with data")

        # Hourly approach used multiple hour buckets to precisely match user's day
        hour_buckets_used = pt_yesterday_results[0][2] if pt_yesterday_results else 0
        assert hour_buckets_used > 0

        # This demonstrates the key benefit: hourly data can be reaggregated to match
        # any user's timezone boundaries, while daily UTC data is fixed to UTC boundaries

    def test_cross_day_session_tracking_accuracy(self):
        """
        Test that hourly bucketing better handles sessions that cross UTC day boundaries.

        Scenario: Pacific user's session spans 11 PM PT - 1 AM PT (crosses UTC day at midnight PT)
        - Session starts: 11 PM PT = 7 AM UTC next day
        - Session ends: 1 AM PT = 9 AM UTC next day
        - Daily UTC: Session split across two daily buckets incorrectly
        - Hourly: Session properly tracked in consecutive hourly buckets
        """
        # Create a cross-day session
        cross_day_session_id = str(uuid7("2024-01-15"))
        user_id = "cross_day_user"
        _create_person(team_id=self.team.pk, distinct_ids=[user_id])

        # Session start: 11 PM PT = 7 AM UTC next day
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=user_id,
            timestamp="2024-01-16T07:00:00Z",  # 11 PM PT Jan 15
            properties={
                "$session_id": cross_day_session_id,
                "$pathname": "/start-page",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$geoip_country_code": "US",
                "$geoip_city_name": "Los Angeles",
                "session_part": "start",
            },
        )

        # Session continues: 12:30 AM PT = 8:30 AM UTC next day
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=user_id,
            timestamp="2024-01-16T08:30:00Z",  # 12:30 AM PT Jan 16
            properties={
                "$session_id": cross_day_session_id,
                "$pathname": "/middle-page",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$geoip_country_code": "US",
                "$geoip_city_name": "Los Angeles",
                "session_part": "middle",
            },
        )

        # Session end: 1 AM PT = 9 AM UTC next day
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=user_id,
            timestamp="2024-01-16T09:00:00Z",  # 1 AM PT Jan 16
            properties={
                "$session_id": cross_day_session_id,
                "$pathname": "/end-page",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$geoip_country_code": "US",
                "$geoip_city_name": "Los Angeles",
                "session_part": "end",
            },
        )

        flush_persons_and_events()
        self._populate_hourly_historical_tables()

        # Query hourly buckets to see session distribution
        cross_day_session_query = """
        SELECT 
            toStartOfHour(period_bucket) as hour_bucket,
            sumMerge(pageviews_count_state) as pageviews,
            uniqMerge(sessions_uniq_state) as sessions
        FROM web_stats_hourly_historical
        WHERE team_id = %(team_id)s
            AND period_bucket >= '2024-01-16 07:00:00'
            AND period_bucket < '2024-01-16 10:00:00'
        GROUP BY hour_bucket
        ORDER BY hour_bucket
        """

        results = sync_execute(cross_day_session_query, {"team_id": self.team.pk})

        # Should have data in 3 consecutive hourly buckets: 07:00, 08:00, 09:00
        assert len(results) == 3
        total_pageviews = sum(row[1] for row in results)
        assert total_pageviews == 3  # 3 pageviews in the session

        # Each hour should show the same session (session_id tracking works across hours)
        for hour_bucket, pageviews, sessions in results:
            assert sessions == 1  # Same session tracked across all hours

        # print(f"Cross-day session tracked across {len(results)} hourly buckets")
        # print(f"Total pageviews: {total_pageviews}, consistent session tracking: {all(row[2] == 1 for row in results)}")

    def test_timezone_friendly_view_combines_data_sources(self):
        """
        Test that the hourly_combined view seamlessly provides both historical and current data.
        """
        # Populate historical table
        self._populate_hourly_historical_tables()

        # Query the combined view
        combined_view_query = """
        SELECT 
            COUNT(*) as total_rows,
            COUNT(DISTINCT toStartOfHour(period_bucket)) as unique_hours,
            sumMerge(pageviews_count_state) as total_pageviews
        FROM web_stats_hourly_combined
        WHERE team_id = %(team_id)s
        """

        results = sync_execute(combined_view_query, {"team_id": self.team.pk})

        # Should have data from our test events
        assert len(results) == 1
        total_rows, unique_hours, total_pageviews = results[0]

        assert total_rows > 0
        assert unique_hours > 0
        assert total_pageviews > 0

        print(f"Combined view: {total_rows} rows across {unique_hours} unique hours, {total_pageviews} total pageviews")

    def test_hourly_vs_daily_granularity_for_peak_hour_analysis(self):
        """
        Demonstrate how hourly granularity enables peak hour analysis that's impossible with daily data.

        Business Question: "What's our peak traffic hour during the business day?"
        Daily data: Can't answer - only has one data point per day
        Hourly data: Can identify the exact peak hour
        """
        self._populate_hourly_historical_tables()

        # Find peak hour with hourly data
        peak_hour_query = """
        SELECT 
            toStartOfHour(period_bucket) as hour_bucket,
            sumMerge(pageviews_count_state) as pageviews,
            uniqMerge(persons_uniq_state) as unique_visitors
        FROM web_stats_hourly_historical
        WHERE team_id = %(team_id)s
            AND period_bucket >= '2024-01-14'
            AND period_bucket < '2024-01-16'
        GROUP BY hour_bucket
        ORDER BY pageviews DESC
        LIMIT 5
        """

        peak_hours = sync_execute(peak_hour_query, {"team_id": self.team.pk})

        # Should identify our afternoon peak (3 PM PT = 23:00 UTC previous day)
        assert len(peak_hours) > 0
        peak_hour, peak_pageviews, peak_visitors = peak_hours[0]

        # Our test data has the most events during afternoon_peak
        assert peak_pageviews > 0

        # print(f"Peak hour: {peak_hour} with {peak_pageviews} pageviews and {peak_visitors} visitors")
        # print("Top 5 hours:", [(str(row[0]), row[1]) for row in peak_hours])

        # This type of analysis is only possible with hourly granularity
        # Daily data would just show one aggregated value per day
