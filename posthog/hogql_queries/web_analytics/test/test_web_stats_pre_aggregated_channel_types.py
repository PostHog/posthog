from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.schema import WebStatsTableQuery, DateRange, HogQLQueryModifiers, WebStatsBreakdown


# @clickhouse_snapshot
class TestWebStatsPreAggregatedChannelTypes(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=["user_paid_search"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_paid_social"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_gad_source"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_direct"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_referral"])

        session_paid_search = str(uuid7("2024-01-01"))
        session_paid_social = str(uuid7("2024-01-01"))
        session_gad_source = str(uuid7("2024-01-01"))
        session_direct = str(uuid7("2024-01-01"))
        session_referral = str(uuid7("2024-01-01"))

        # Session 1: Paid Search (Google Ads via gclid)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_paid_search",
            timestamp="2024-01-01T10:00:00Z",
            properties={
                "$session_id": session_paid_search,
                "$current_url": "https://example.com/landing?gclid=abc123",
                "gclid": "abc123",
                "$referring_domain": "google.com",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_paid_search",
            timestamp="2024-01-01T10:05:00Z",
            properties={
                "$session_id": session_paid_search,
                "$current_url": "https://example.com/signup",
            },
        )

        # Session 2: Paid Social (Facebook)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_paid_social",
            timestamp="2024-01-01T11:00:00Z",
            properties={
                "$session_id": session_paid_social,
                "$current_url": "https://example.com/landing?fbclid=xyz789",
                "fbclid": "xyz789",
                "$referring_domain": "facebook.com",
            },
        )

        # Session 3: Paid Search (Google Ads via gad_source)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_gad_source",
            timestamp="2024-01-01T12:00:00Z",
            properties={
                "$session_id": session_gad_source,
                "$current_url": "https://example.com/features?gad_source=1",
                "gad_source": "1",
                "$referring_domain": "google.com",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_gad_source",
            timestamp="2024-01-01T12:05:00Z",
            properties={
                "$session_id": session_gad_source,
                "$current_url": "https://example.com/pricing",
            },
        )

        # Session 4: Direct traffic (no attribution)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_direct",
            timestamp="2024-01-01T13:00:00Z",
            properties={
                "$session_id": session_direct,
                "$current_url": "https://example.com/",
                "$referring_domain": "$direct",
            },
        )

        # Session 5: Referral traffic
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_referral",
            timestamp="2024-01-01T14:00:00Z",
            properties={
                "$session_id": session_referral,
                "$current_url": "https://example.com/features",
                "$referring_domain": "techcrunch.com",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_referral",
            timestamp="2024-01-01T14:02:00Z",
            properties={
                "$session_id": session_referral,
                "$current_url": "https://example.com/about",
            },
        )

        flush_persons_and_events()

        self._populate_web_stats_tables()

    def _populate_web_stats_tables(self):
        select_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[self.team.pk],
            table_name="web_stats_daily",
            select_only=True,
        )
        insert_sql = f"INSERT INTO web_stats_daily\n{select_sql}"
        sync_execute(insert_sql)

    def test_channel_type_breakdown_with_stats_table_runner(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=[],
            breakdownBy=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
            limit=100,
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
        )
        runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=modifiers)
        response = runner.calculate()

        results_by_channel = {}
        for result in response.results:
            if isinstance(result, list):
                channel = result[0] if len(result) > 0 else "Unknown"
                visitors = result[1] if len(result) > 1 else (0, 0)
                views = result[2] if len(result) > 2 else (0, 0)
                results_by_channel[channel] = {
                    "pageviews": views[0] if isinstance(views, tuple) else views,
                    "sessions": visitors[0] if isinstance(visitors, tuple) else visitors,
                    "persons": visitors[0] if isinstance(visitors, tuple) else visitors,
                }
            else:
                # Original object format
                channel = result.breakdown_value
                results_by_channel[channel] = {
                    "pageviews": result.views,
                    "sessions": result.sessions,
                    "persons": result.visitors,
                }

        total_pageviews = sum(metrics["pageviews"] for metrics in results_by_channel.values())
        total_sessions = sum(metrics["sessions"] for metrics in results_by_channel.values())
        total_persons = sum(metrics["persons"] for metrics in results_by_channel.values())

        assert total_pageviews == 8, f"Expected 8 pageviews, got {total_pageviews}"
        assert total_sessions == 5, f"Expected 5 sessions, got {total_sessions}"
        assert total_persons == 5, f"Expected 5 persons, got {total_persons}"

    def test_channel_type_consistency_preagg_vs_regular(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=[],
            breakdownBy=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
            limit=100,
        )

        preagg_modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
        )
        preagg_runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=preagg_modifiers)
        preagg_response = preagg_runner.calculate()

        regular_modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False,
        )
        regular_runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=regular_modifiers)
        regular_response = regular_runner.calculate()

        def results_to_dict(results):
            result_dict = {}
            for result in results:
                if isinstance(result, list):
                    channel = result[0] if len(result) > 0 else "Unknown"
                    visitors = result[1] if len(result) > 1 else (0, 0)
                    views = result[2] if len(result) > 2 else (0, 0)
                    result_dict[channel] = {
                        "pageviews": views[0] if isinstance(views, tuple) else views,
                        "sessions": visitors[0] if isinstance(visitors, tuple) else visitors,
                        "persons": visitors[0] if isinstance(visitors, tuple) else visitors,
                    }
                else:
                    result_dict[result.breakdown_value] = {
                        "pageviews": result.views,
                        "sessions": result.sessions,
                        "persons": result.visitors,
                    }
            return result_dict

        preagg_dict = results_to_dict(preagg_response.results)
        regular_dict = results_to_dict(regular_response.results)

        # Verify both queries used their respective table types
        assert preagg_response.usedPreAggregatedTables
        assert not regular_response.usedPreAggregatedTables

        assert preagg_dict == regular_dict
