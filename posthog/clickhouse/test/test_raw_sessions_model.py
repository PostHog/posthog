import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.models.raw_sessions.sessions_v2 import RAW_SESSION_TABLE_BACKFILL_SELECT_SQL
from posthog.models.utils import uuid7

distinct_id_counter = 0
session_id_counter = 0


def create_distinct_id():
    global distinct_id_counter
    distinct_id_counter += 1
    return f"d{distinct_id_counter}"


def create_session_id():
    global session_id_counter
    session_id_counter += 1
    return str(uuid7(random=session_id_counter))


class TestRawSessionsModel(ClickhouseTestMixin, BaseTest):
    def select_by_session_id(self, session_id):
        return query_with_columns(
            """
            select
                *
            from raw_sessions_v
            where
                session_id_v7 = toUInt128(toUUID(%(session_id)s))  AND
                team_id = %(team_id)s
                """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )

    def test_it_creates_session_when_creating_event(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp="2024-03-08",
        )

        response = sync_execute(
            """
            select
                session_id_v7,
                team_id
            from raw_sessions_v
            where
                session_id_v7 = toUInt128(toUUID(%(session_id)s))  AND
                team_id = %(team_id)s
                """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )

        self.assertEqual(len(response), 1)

    def test_handles_different_distinct_id_across_same_session(self):
        distinct_id1 = create_distinct_id()
        distinct_id2 = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id1,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id2,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )

        responses = self.select_by_session_id(session_id)
        self.assertEqual(len(responses), 1)
        self.assertIn(responses[0]["distinct_id"], {distinct_id1, distinct_id2})
        self.assertEqual(responses[0]["pageview_count"], 2)

    def test_handles_entry_and_exit_urls(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/entry", "$session_id": session_id},
            timestamp="2024-03-08:01",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/middle", "$session_id": session_id},
            timestamp="2024-03-08:02",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/middle", "$session_id": session_id},
            timestamp="2024-03-08:03",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/exit", "$session_id": session_id},
            timestamp="2024-03-08:04",
        )

        responses = self.select_by_session_id(session_id)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["entry_url"], "/entry")
        self.assertEqual(responses[0]["end_url"], "/exit")
        self.assertEqual(len(responses[0]["urls"]), 3)
        self.assertEqual(set(responses[0]["urls"]), {"/entry", "/middle", "/exit"})  # order is not guaranteed

    def test_handles_initial_utm_properties(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id, "utm_source": "source"},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id, "utm_source": "other_source"},
            timestamp="2024-03-08",
        )

        responses = self.select_by_session_id(session_id)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["initial_utm_source"], "source")

    def test_counts_pageviews_autocaptures_and_events(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="other event",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$pageleave",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )

        responses = self.select_by_session_id(session_id)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["pageview_count"], 1)
        self.assertEqual(responses[0]["autocapture_count"], 2)

    def test_separates_sessions_across_same_user(self):
        distinct_id = create_distinct_id()
        session_id1 = create_session_id()
        session_id2 = create_session_id()
        session_id3 = create_session_id()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id1},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id2},
            timestamp="2024-03-08",
        )

        responses = self.select_by_session_id(session_id1)
        self.assertEqual(len(responses), 1)
        responses = self.select_by_session_id(session_id2)
        self.assertEqual(len(responses), 1)
        responses = self.select_by_session_id(session_id3)
        self.assertEqual(len(responses), 0)

    def test_select_from_sessions(self):
        # just make sure that we can select from the sessions table without error
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )

        # we can't include all the columns as this clickhouse driver doesn't support selecting states
        responses = sync_execute(
            """
        SELECT
            session_id_v7,
            team_id,
            min_timestamp,
            max_timestamp,
            urls,
            pageview_count,
            autocapture_count
        FROM raw_sessions
        WHERE session_id_v7 = toUInt128(toUUID(%(session_id)s)) AND team_id = %(team_id)s
        """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )
        self.assertEqual(len(responses), 1)

    def test_select_from_sessions_mv(self):
        # just make sure that we can select from the sessions mv without error
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )

        # we can't include all the columns as this clickhouse driver doesn't support selecting states
        responses = sync_execute(
            """
        SELECT
            session_id_v7,
            team_id,
            min_timestamp,
            max_timestamp,
            urls,
            pageview_count,
            autocapture_count
        FROM raw_sessions_mv
        WHERE session_id_v7 = toUInt128(toUUID(%(session_id)s)) AND team_id = %(team_id)s
        """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )
        self.assertEqual(len(responses), 1)

    def test_ignores_empty_lcp(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        # it should read the first valid non-null value
        _create_event(
            team=self.team,
            event="$web_vitals",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$web_vitals",
            distinct_id=distinct_id,
            properties={"$session_id": session_id, "$web_vitals": "notafloat"},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$web_vitals",
            distinct_id=distinct_id,
            properties={"$session_id": session_id, "$web_vitals_LCP_value": 42},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$web_vitals",
            distinct_id=distinct_id,
            properties={"$session_id": session_id, "$web_vitals_LCP_value": 43},
            timestamp="2024-03-08",
        )

        responses = self.select_by_session_id(session_id)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["vitals_lcp"], 42)

    def test_backfill_sql(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp="2024-03-08",
        )

        # just test that the backfill SQL can be run without error
        sync_execute(
            "INSERT INTO raw_sessions" + RAW_SESSION_TABLE_BACKFILL_SELECT_SQL() + "AND team_id = %(team_id)s",
            {"team_id": self.team.id},
        )

    def test_max_inserted_at(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        now = datetime.datetime.now(datetime.UTC)

        result = self.select_by_session_id(session_id)
        max_inserted_at = result[0]["max_inserted_at"]
        # assert that it's close to now, allowing for a small margin of error because we're running this on CI in the cloud somewhere with preempting
        self.assertTrue(
            abs((max_inserted_at - now).total_seconds()) < 10,
        )
