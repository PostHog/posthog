from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_sessions import ClickhouseSessions
from posthog.queries.test.test_sessions import TestSessions


class TestClickhouseSessions(TestSessions):
    session = ClickhouseSessions

    def test_sessions_list(self):
        create_event(team=self.team, event="1st action", distinct_id="1", timestamp="2012-01-14 03:21:34")
        create_event(team=self.team, event="1st action", distinct_id="2", timestamp="2012-01-14 03:21:34")

        create_event(team=self.team, event="2nd action", distinct_id="1", timestamp="2012-01-14 03:25:34")
        create_event(team=self.team, event="2nd action", distinct_id="2", timestamp="2012-01-14 03:25:34")

        create_event(team=self.team, event="3rd action", distinct_id="2", timestamp="2012-01-15 03:59:34")

        create_event(team=self.team, event="3rd action", distinct_id="1", timestamp="2012-01-15 03:59:35")

        create_event(
            team=self.team,
            event="4th action",
            distinct_id="1",
            timestamp="2012-01-15 04:01:34",
            properties={"$os": "Mac OS X"},
        )
        create_event(
            team=self.team,
            event="4th action",
            distinct_id="2",
            timestamp="2012-01-15 04:01:34",
            properties={"$os": "Windows 95"},
        )

        self.sessions_list()

    def test_sessions_avg_length(self):
        self.sessions_avg_length()

    def test_sessions_avg_length_interval(self):
        self.sessions_avg_length_interval()

    def test_no_events(self):
        self.no_events()

    def test_compare_sessions(self):
        self.compare_sessions()

    def test_sessions_count_buckets(self):
        self.sessions_count_buckets()
