from freezegun import freeze_time

from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL
from posthog.models.utils import uuid7
from posthog.test.base import flush_persons_and_events
from posthog.hogql_queries.web_analytics.test.base import WebAnalyticsPreAggregatedTestBase


class TestWebBouncesWithMaterialized(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        """Set up diverse test scenarios for bounce and session duration validation"""
        # Session 1: Anonymous -> Identified user (10 minutes, 3 pageviews - NOT a bounce)
        self.anon1_id = self._create_test_person("anon1")
        self.user1_id = self._create_test_person("user1")
        self.session1_id = str(uuid7())

        # Session 2: Single page bounce (0 minutes, 1 pageview - IS a bounce)
        self.user2_id = self._create_test_person("user2")
        self.session2_id = str(uuid7())

        # Session 3: Long multi-page session (15 minutes, 4 pageviews - NOT a bounce)
        self.user3_id = self._create_test_person("user3")
        self.session3_id = str(uuid7())

        # Session 4: Another bounce (0 minutes, 1 pageview - IS a bounce)
        self.user4_id = self._create_test_person("user4")
        self.session4_id = str(uuid7())

        # Session 5: Quick two-page session (2 minutes, 2 pageviews - NOT a bounce)
        self.user5_id = self._create_test_person("user5")
        self.session5_id = str(uuid7())

        # Create Session 1 events: Anonymous -> Identified (10 minutes, 3 pageviews)
        with freeze_time("2024-01-01T10:00:00Z"):
            self._create_session_event(
                self.anon1_id, self.session1_id, "2024-01-01T10:00:00Z", "https://example.com/landing"
            )

        with freeze_time("2024-01-01T10:05:00Z"):
            self._create_session_event(
                self.user1_id, self.session1_id, "2024-01-01T10:05:00Z", "https://example.com/signup"
            )

        with freeze_time("2024-01-01T10:10:00Z"):
            self._create_session_event(
                self.user1_id, self.session1_id, "2024-01-01T10:10:00Z", "https://example.com/dashboard"
            )

        # Create Session 2: Single page bounce (0 minutes, 1 pageview)
        with freeze_time("2024-01-01T11:00:00Z"):
            self._create_session_event(
                self.user2_id,
                self.session2_id,
                "2024-01-01T11:00:00Z",
                "https://example.com/landing",
                extra_properties={
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 375,
                    "$viewport_height": 812,
                },
            )

        # Create Session 3: Long session (15 minutes, 4 pageviews)
        session3_events = [
            ("2024-01-01T12:00:00Z", "https://example.com/landing"),
            ("2024-01-01T12:05:00Z", "https://example.com/features"),
            ("2024-01-01T12:10:00Z", "https://example.com/pricing"),
            ("2024-01-01T12:15:00Z", "https://example.com/contact"),
        ]
        self._create_session_with_events(
            self.user3_id,
            self.session3_id,
            session3_events,
            extra_properties={
                "$device_type": "Desktop",
                "$browser": "Firefox",
                "$os": "macOS",
                "$viewport_width": 1440,
                "$viewport_height": 900,
            },
        )

        # Create Session 4: Another bounce (0 minutes, 1 pageview)
        with freeze_time("2024-01-01T13:00:00Z"):
            self._create_session_event(
                self.user4_id,
                self.session4_id,
                "2024-01-01T13:00:00Z",
                "https://example.com/pricing",
                extra_properties={
                    "$device_type": "Tablet",
                    "$browser": "Chrome",
                    "$os": "Android",
                    "$viewport_width": 768,
                    "$viewport_height": 1024,
                },
            )

        # Create Session 5: Quick two-page session (2 minutes, 2 pageviews)
        session5_events = [
            ("2024-01-01T14:00:00Z", "https://example.com/features"),
            ("2024-01-01T14:02:00Z", "https://example.com/signup"),
        ]
        self._create_session_with_events(
            self.user5_id,
            self.session5_id,
            session5_events,
            extra_properties={"$device_type": "Desktop", "$browser": "Edge", "$os": "Windows"},
        )

        flush_persons_and_events()

    def _get_expected_metrics(self) -> dict:
        """Return expected metrics for the test scenarios"""
        return {
            "unique_persons": 5,
            "total_pageviews": 11,  # 3+1+4+1+2 = 11
            "unique_sessions": 5,
            "bounce_sessions": 2,  # Sessions 2 and 4
            "bounce_rate": 2 / 5,  # 0.4 (40%)
            "avg_session_duration": (600 + 0 + 900 + 0 + 120) / 5,  # 324.0 seconds
        }

    def test_web_bounces_table_match_expected_metrics(self):
        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )

        actual_metrics = self._execute_metrics_query(sql)

        unique_persons, total_pageviews, unique_sessions, avg_duration, bounce_sessions, bounce_rate = actual_metrics

        assert unique_persons == 5
        assert total_pageviews == 11  # 3+1+4+1+2 = 11
        assert unique_sessions == 5
        assert bounce_sessions == 2  # Sessions 2 and 4
        assert abs(bounce_rate - 0.4) < 0.01  # 2/5 = 0.4
        assert abs(avg_duration - 324.0) < 1.0  # (600 + 0 + 900 + 0 + 120) / 5 = 324.0

    def test_preagg_vs_raw_events_comparison(self):
        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )
        preagg_metrics = self._execute_metrics_query(sql)

        raw_metrics = self._execute_raw_events_metrics_query("2024-01-01", "2024-01-02")

        self._compare_preagg_vs_raw_metrics(preagg_metrics, raw_metrics)

        # Also validate against expected values for extra confidence
        expected_metrics = self._get_expected_metrics()
        self._validate_metrics(preagg_metrics, expected_metrics)
        self._validate_metrics(raw_metrics, expected_metrics)

    def test_weboverview_queryrunner_comparison(self):
        """Test that demonstrates WebOverviewQueryRunner works with simple test data"""
        from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
        from posthog.schema import WebOverviewQuery, DateRange, HogQLQueryModifiers, SessionTableVersion
        from posthog.models.utils import uuid7
        from posthog.test.base import _create_event, _create_person, flush_persons_and_events
        
        # Create simple test data similar to existing WebOverview tests
        s1 = str(uuid7("2024-01-01"))
        s2 = str(uuid7("2024-01-01"))
        
        # Create persons (use different distinct_ids to avoid conflicts)
        with freeze_time("2024-01-01T10:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=["weboverview_user1"])
            _create_person(team_id=self.team.pk, distinct_ids=["weboverview_user2"])
        
        # Create simple events that should work with WebOverview
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="weboverview_user1",
            timestamp="2024-01-01T10:00:00Z",
            properties={"$session_id": s1, "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview", 
            distinct_id="weboverview_user1",
            timestamp="2024-01-01T10:05:00Z",
            properties={"$session_id": s1, "$current_url": "https://example.com/page2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="weboverview_user2", 
            timestamp="2024-01-01T11:00:00Z",
            properties={"$session_id": s2, "$current_url": "https://example.com/page1"},
        )
        
        flush_persons_and_events()
        
        # Create WebOverview query
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-01"),
            properties=[],
            compareFilter=None,
        )
        
        # Query without pre-aggregated tables
        modifiers_regular = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False,
            sessionTableVersion=SessionTableVersion.V2
        )
        runner_regular = WebOverviewQueryRunner(query=query, team=self.team, modifiers=modifiers_regular)
        
        # Execute query
        response_regular = runner_regular.calculate()
        
        # Extract WebOverview results
        weboverview_results = {item.key: item.value for item in response_regular.results}
        
        assert weboverview_results.get("visitors", 0) == 2
        assert weboverview_results.get("views", 0) == 3
        assert weboverview_results.get("sessions", 0) == 2
        
        # Now get pre-aggregated metrics for the same date range and compare
        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )
        preagg_metrics = self._execute_metrics_query(sql)
        
        # Convert to dict for easier comparison
        preagg_results = {
            "unique_persons": preagg_metrics[0],
            "total_pageviews": preagg_metrics[1], 
            "unique_sessions": preagg_metrics[2],
            "avg_session_duration": preagg_metrics[3],
            "bounce_sessions": preagg_metrics[4],
            "bounce_rate": preagg_metrics[5],
        }
        
        # Compare the overlapping metrics
        # Note: The pre-agg query includes data from our main test setup (5 users, 11 pageviews, 5 sessions)
        # plus the WebOverview test data (2 users, 3 pageviews, 2 sessions)
        # So totals should be: 7 users, 14 pageviews, 7 sessions
        
        expected_total_persons = 5 + 2  # Main test data + WebOverview test data
        expected_total_pageviews = 11 + 3  # Main test data + WebOverview test data  
        expected_total_sessions = 5 + 2  # Main test data + WebOverview test data
        
        assert preagg_results["unique_persons"] == expected_total_persons, (
            f"Pre-agg unique persons should be {expected_total_persons}, got {preagg_results['unique_persons']}"
        )
        assert preagg_results["total_pageviews"] == expected_total_pageviews, (
            f"Pre-agg total pageviews should be {expected_total_pageviews}, got {preagg_results['total_pageviews']}"
        )
        assert preagg_results["unique_sessions"] == expected_total_sessions, (
            f"Pre-agg unique sessions should be {expected_total_sessions}, got {preagg_results['unique_sessions']}"
        )
        
        # The key validation: WebOverview and pre-agg queries both work on the same underlying data
        # and produce consistent results when accounting for the data scope differences
    
    def test_isolated_weboverview_vs_preagg_comparison(self):
        """Test that compares WebOverview and pre-agg results on identical isolated dataset"""
        from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
        from posthog.schema import WebOverviewQuery, DateRange, HogQLQueryModifiers, SessionTableVersion
        from posthog.models.utils import uuid7
        from posthog.test.base import _create_event, _create_person, flush_persons_and_events
        from posthog.clickhouse.client.execute import sync_execute
        
        # Create a completely isolated test with different date to avoid interference
        test_date = "2024-02-01"
        
        # Create isolated test data
        s1 = str(uuid7("2024-02-01"))
        s2 = str(uuid7("2024-02-01"))
        s3 = str(uuid7("2024-02-01"))
        
        with freeze_time("2024-02-01T10:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=["isolated_user1"])
            _create_person(team_id=self.team.pk, distinct_ids=["isolated_user2"])
            _create_person(team_id=self.team.pk, distinct_ids=["isolated_user3"])
        
        # Session 1: 2 pageviews (non-bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="isolated_user1",
            timestamp="2024-02-01T10:00:00Z",
            properties={"$session_id": s1, "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="isolated_user1", 
            timestamp="2024-02-01T10:05:00Z",
            properties={"$session_id": s1, "$current_url": "https://example.com/page2"},
        )
        
        # Session 2: 1 pageview (bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="isolated_user2",
            timestamp="2024-02-01T11:00:00Z", 
            properties={"$session_id": s2, "$current_url": "https://example.com/page1"},
        )
        
        # Session 3: 3 pageviews (non-bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="isolated_user3",
            timestamp="2024-02-01T12:00:00Z",
            properties={"$session_id": s3, "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="isolated_user3",
            timestamp="2024-02-01T12:03:00Z",
            properties={"$session_id": s3, "$current_url": "https://example.com/page2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="isolated_user3",
            timestamp="2024-02-01T12:06:00Z",
            properties={"$session_id": s3, "$current_url": "https://example.com/page3"},
        )
        
        flush_persons_and_events()
        
        # Expected metrics: 
        # - 3 users, 6 pageviews, 3 sessions, 1 bounce (33.33% bounce rate)
        # - Session durations: 300s (5 min), 0s (bounce), 360s (6 min) = avg 220s
        
        # Get WebOverview results
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=test_date, date_to=test_date),
            properties=[],
            compareFilter=None,
        )
        
        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False,
            sessionTableVersion=SessionTableVersion.V2
        )
        runner = WebOverviewQueryRunner(query=query, team=self.team, modifiers=modifiers)
        weboverview_response = runner.calculate()
        
        weboverview_results = {item.key: item.value for item in weboverview_response.results}
        
        # Get pre-aggregated results for the same date
        preagg_sql = WEB_BOUNCES_INSERT_SQL(
            date_start=test_date, date_end="2024-02-02", team_ids=[self.team.pk], select_only=True
        )
        
        # Get all pre-aggregated results and filter manually since the query returns aggregated states
        all_preagg_results = self._execute_metrics_query(preagg_sql)
        
        # For this test, we know the isolated data should be the only data for 2024-02-01
        # So the pre-agg results should match our expected isolated results
        isolated_persons, isolated_pageviews, isolated_sessions, isolated_duration, isolated_bounces, isolated_bounce_rate = all_preagg_results
        
        # Compare the results - this is the key validation!
        print(f"WebOverview: visitors={weboverview_results.get('visitors')}, views={weboverview_results.get('views')}, sessions={weboverview_results.get('sessions')}")
        print(f"Pre-agg: persons={isolated_persons}, pageviews={isolated_pageviews}, sessions={isolated_sessions}")
        
        # Validate that both queries produce the same results on the same data
        assert weboverview_results.get('visitors') == isolated_persons, (
            f"Visitors mismatch: WebOverview={weboverview_results.get('visitors')}, Pre-agg={isolated_persons}"
        )
        assert weboverview_results.get('views') == isolated_pageviews, (
            f"Views mismatch: WebOverview={weboverview_results.get('views')}, Pre-agg={isolated_pageviews}"
        )
        assert weboverview_results.get('sessions') == isolated_sessions, (
            f"Sessions mismatch: WebOverview={weboverview_results.get('sessions')}, Pre-agg={isolated_sessions}"
        )
        
        # Compare session duration (this is critical for validating the PR changes!)
        weboverview_duration = weboverview_results.get('session duration', 0) or 0
        print(f"Session duration comparison: WebOverview={weboverview_duration}s, Pre-agg={isolated_duration}s")
        
        # Allow small tolerance for floating point differences
        duration_diff = abs(weboverview_duration - isolated_duration)
        assert duration_diff < 1.0, (
            f"Session duration mismatch: WebOverview={weboverview_duration}s, "
            f"Pre-agg={isolated_duration}s, diff={duration_diff}s"
        )
        
        # Compare bounce rate (another critical metric!)
        weboverview_bounce_rate_raw = weboverview_results.get('bounce rate', 0) or 0
        # WebOverview returns bounce rate as percentage, convert to decimal for comparison
        weboverview_bounce_rate = weboverview_bounce_rate_raw / 100.0
        print(f"Bounce rate comparison: WebOverview={weboverview_bounce_rate_raw}% ({weboverview_bounce_rate:.4f}), Pre-agg={isolated_bounce_rate:.4f}")
        
        # Allow small tolerance for floating point differences
        bounce_rate_diff = abs(weboverview_bounce_rate - isolated_bounce_rate)
        assert bounce_rate_diff < 0.01, (
            f"Bounce rate mismatch: WebOverview={weboverview_bounce_rate:.4f}, "
            f"Pre-agg={isolated_bounce_rate:.4f}, diff={bounce_rate_diff:.4f}"
        )
        
        # Also validate the expected values for our test scenario
        assert isolated_persons == 3, f"Expected 3 persons, got {isolated_persons}"
        assert isolated_pageviews == 6, f"Expected 6 pageviews, got {isolated_pageviews}"
        assert isolated_sessions == 3, f"Expected 3 sessions, got {isolated_sessions}"
        assert isolated_bounces == 1, f"Expected 1 bounce, got {isolated_bounces}"
        assert abs(isolated_bounce_rate - 1/3) < 0.01, f"Expected 33.33% bounce rate, got {isolated_bounce_rate}"
        
        # Validate expected session duration: (300 + 0 + 360) / 3 = 220 seconds
        expected_avg_duration = (300 + 0 + 360) / 3  # 220 seconds
        assert abs(isolated_duration - expected_avg_duration) < 1.0, (
            f"Expected avg session duration {expected_avg_duration}s, got {isolated_duration}s"
        )
        
        # SUCCESS: This test proves that WebOverview and pre-aggregated queries 
        # produce identical results when working on the same underlying data!

