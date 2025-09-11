from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from posthog.schema import DateRange, HogQLQueryModifiers, SessionTableVersion, WebOverviewQuery

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL


class TestWebBouncesPreAggregated(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=["anon1"])
            _create_person(team_id=self.team.pk, distinct_ids=["user1"])
            _create_person(team_id=self.team.pk, distinct_ids=["user2"])
            _create_person(team_id=self.team.pk, distinct_ids=["user3"])
            _create_person(team_id=self.team.pk, distinct_ids=["user4"])
            _create_person(team_id=self.team.pk, distinct_ids=["user5"])

        self.session1_id = str(uuid7("2024-01-01"))
        self.session2_id = str(uuid7("2024-01-01"))
        self.session3_id = str(uuid7("2024-01-01"))
        self.session4_id = str(uuid7("2024-01-01"))
        self.session5_id = str(uuid7("2024-01-01"))

        # Session 1: Anonymous -> Identified user (10 minutes, 3 pageviews - NOT a bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="anon1",
            timestamp="2024-01-01T10:00:00Z",
            properties={"$session_id": self.session1_id, "$current_url": "https://example.com/landing"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",  # Same session but user identifies mid-session
            timestamp="2024-01-01T10:05:00Z",
            properties={"$session_id": self.session1_id, "$current_url": "https://example.com/signup"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01T10:10:00Z",
            properties={"$session_id": self.session1_id, "$current_url": "https://example.com/dashboard"},
        )

        # Session 2: Single page bounce (0 minutes, 1 pageview - IS a bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01T11:00:00Z",
            properties={"$session_id": self.session2_id, "$current_url": "https://example.com/landing"},
        )

        # Session 3: Long multi-page session (15 minutes, 4 pageviews - NOT a bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01T12:00:00Z",
            properties={"$session_id": self.session3_id, "$current_url": "https://example.com/landing"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01T12:05:00Z",
            properties={"$session_id": self.session3_id, "$current_url": "https://example.com/features"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01T12:10:00Z",
            properties={"$session_id": self.session3_id, "$current_url": "https://example.com/pricing"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01T12:15:00Z",
            properties={"$session_id": self.session3_id, "$current_url": "https://example.com/contact"},
        )

        # Session 4: Another bounce (0 minutes, 1 pageview - IS a bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user4",
            timestamp="2024-01-01T13:00:00Z",
            properties={"$session_id": self.session4_id, "$current_url": "https://example.com/pricing"},
        )

        # Session 5: Quick two-page session (2 minutes, 2 pageviews - NOT a bounce)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user5",
            timestamp="2024-01-01T14:00:00Z",
            properties={"$session_id": self.session5_id, "$current_url": "https://example.com/features"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user5",
            timestamp="2024-01-01T14:02:00Z",
            properties={"$session_id": self.session5_id, "$current_url": "https://example.com/signup"},
        )

        flush_persons_and_events()

    def _get_pre_agg_metrics_from_bounce_table(self, base_sql: str) -> tuple:
        metrics_sql = f"""
        WITH session_data AS (
            {base_sql}
        ),
        aggregated AS (
            SELECT
                uniqMerge(persons_uniq_state) AS unique_persons,
                sumMerge(pageviews_count_state) AS total_pageviews,
                uniqMerge(sessions_uniq_state) AS unique_sessions,
                sumMerge(total_session_duration_state) AS total_duration,
                sumMerge(total_session_count_state) AS total_session_count,
                sumMerge(bounces_count_state) AS bounce_sessions
            FROM session_data
        )
        SELECT
            unique_persons,
            total_pageviews,
            unique_sessions,
            if(total_session_count > 0, total_duration / total_session_count, 0) AS avg_session_duration,
            bounce_sessions,
            if(unique_sessions > 0, bounce_sessions / unique_sessions, 0) AS bounce_rate
        FROM aggregated
        """

        results = sync_execute(metrics_sql)
        assert len(results) == 1
        return results[0]

    def _validate_metrics(self, actual_metrics: tuple, expected_metrics: dict):
        unique_persons, total_pageviews, unique_sessions, avg_duration, bounce_sessions, bounce_rate = actual_metrics

        assert unique_persons == expected_metrics["unique_persons"]
        assert total_pageviews == expected_metrics["total_pageviews"]
        assert unique_sessions == expected_metrics["unique_sessions"]
        assert bounce_sessions == expected_metrics["bounce_sessions"]
        assert abs(bounce_rate - expected_metrics["bounce_rate"]) < 0.01
        assert abs(avg_duration - expected_metrics["avg_session_duration"]) < 1.0

    def _get_metrics_from_raw_events(self, date_start: str = "2024-01-01", date_end: str = "2024-01-02") -> tuple:
        raw_metrics_sql = f"""
        WITH session_metrics AS (
            SELECT
                argMax(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id), e.timestamp) AS person_id,
                countIf(e.event IN ('$pageview', '$screen')) AS pageview_count,
                e.`$session_id` AS session_id,
                min(e.timestamp) AS min_timestamp,
                max(e.timestamp) AS max_timestamp,
                dateDiff('second', min(e.timestamp), max(e.timestamp)) AS session_duration
            FROM events AS e
            LEFT JOIN
            (
                SELECT
                    argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                    person_distinct_id_overrides.distinct_id AS distinct_id
                FROM person_distinct_id_overrides
                WHERE team_id = {self.team.pk}
                GROUP BY person_distinct_id_overrides.distinct_id
                HAVING ifNull(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version) = 0, 0)
            ) AS events__override ON e.distinct_id = events__override.distinct_id
            WHERE e.team_id = {self.team.pk}
                AND e.event IN ('$pageview', '$screen')
                AND e.`$session_id` IS NOT NULL
                AND e.timestamp >= toDateTime('{date_start}', 'UTC')
                AND e.timestamp < toDateTime('{date_end}', 'UTC')
            GROUP BY e.`$session_id`
        )
        SELECT
            uniq(person_id) AS unique_persons,
            sum(pageview_count) AS total_pageviews,
            uniq(session_id) AS unique_sessions,
            if(count(*) > 0, sum(session_duration) / count(*), 0) AS avg_session_duration,
            sumIf(1, session_duration = 0) AS bounce_sessions,
            if(count(*) > 0, sumIf(1, session_duration = 0) / count(*), 0) AS bounce_rate
        FROM session_metrics
        """

        results = sync_execute(raw_metrics_sql)
        assert len(results) == 1
        return results[0]

    def _compare_preagg_vs_raw_metrics(self, preagg_metrics: tuple, raw_metrics: tuple, tolerance: float = 1.0):
        preagg_persons, preagg_pageviews, preagg_sessions, preagg_duration, preagg_bounces, preagg_bounce_rate = (
            preagg_metrics
        )
        raw_persons, raw_pageviews, raw_sessions, raw_duration, raw_bounces, raw_bounce_rate = raw_metrics

        assert preagg_persons == raw_persons
        assert preagg_pageviews == raw_pageviews
        assert preagg_sessions == raw_sessions
        assert preagg_bounces == raw_bounces
        assert abs(preagg_duration - raw_duration) < tolerance
        assert abs(preagg_bounce_rate - raw_bounce_rate) < 0.01

    def _get_expected_metrics(self) -> dict:
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

        actual_metrics = self._get_pre_agg_metrics_from_bounce_table(sql)

        unique_persons, total_pageviews, unique_sessions, avg_duration, bounce_sessions, bounce_rate = actual_metrics

        assert unique_persons == 5
        assert total_pageviews == 11
        assert unique_sessions == 5
        assert bounce_sessions == 2
        assert abs(bounce_rate - 0.4) < 0.01
        assert abs(avg_duration - 324.0) < 1.0

    def test_preagg_vs_raw_events_comparison(self):
        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )
        preagg_metrics = self._get_pre_agg_metrics_from_bounce_table(sql)

        raw_metrics = self._get_metrics_from_raw_events("2024-01-01", "2024-01-02")

        self._compare_preagg_vs_raw_metrics(preagg_metrics, raw_metrics)

        expected_metrics = self._get_expected_metrics()
        self._validate_metrics(preagg_metrics, expected_metrics)
        self._validate_metrics(raw_metrics, expected_metrics)

    def test_weboverview_queryrunner_comparison(self):
        expected_metrics = self._get_expected_metrics()

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=[],
            compareFilter=None,
        )
        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False, sessionTableVersion=SessionTableVersion.V2
        )
        runner = WebOverviewQueryRunner(query=query, team=self.team, modifiers=modifiers)
        weboverview_response = runner.calculate()
        weboverview_results = {item.key: item.value for item in weboverview_response.results}

        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )
        preagg_metrics = self._get_pre_agg_metrics_from_bounce_table(sql)
        persons, pageviews, sessions, duration, bounces, bounce_rate = preagg_metrics

        assert weboverview_results.get("visitors") == persons
        assert weboverview_results.get("views") == pageviews
        assert weboverview_results.get("sessions") == sessions

        weboverview_duration = weboverview_results.get("session duration", 0) or 0
        duration_diff = abs(weboverview_duration - duration)
        assert duration_diff < 1.0

        weboverview_bounce_rate_raw = weboverview_results.get("bounce rate", 0) or 0
        weboverview_bounce_rate = weboverview_bounce_rate_raw / 100.0

        bounce_rate_diff = abs(weboverview_bounce_rate - bounce_rate)
        assert bounce_rate_diff < 0.01

        assert persons == expected_metrics["unique_persons"]
        assert pageviews == expected_metrics["total_pageviews"]
        assert sessions == expected_metrics["unique_sessions"]
        assert bounce_rate == expected_metrics["bounce_rate"]
        assert duration == expected_metrics["avg_session_duration"]
