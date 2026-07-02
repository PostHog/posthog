from posthog.test.base import BaseTest, ClickhouseDestroyTablesMixin, ClickhouseTestMixin, _create_event

from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.models import Team

distinct_id_counter = 0
session_id_counter = 0


def create_distinct_id():
    global distinct_id_counter
    distinct_id_counter += 1
    return f"d{distinct_id_counter}"


def create_session_id():
    global session_id_counter
    session_id_counter += 1
    return f"s{session_id_counter}"


# only certain team ids can insert events into this legacy sessions table, see sessions/sql.py for more info
TEAM_ID = 2
TEAM = Team(id=TEAM_ID)


class TestSessionsModel(ClickhouseDestroyTablesMixin, ClickhouseTestMixin, BaseTest):
    def select_by_session_id(self, session_id):
        return query_with_columns(
            """
            select
                *
            from sessions_v
            where
                session_id = %(session_id)s AND
                team_id = %(team_id)s
                """,
            {
                "session_id": session_id,
                "team_id": TEAM_ID,
            },
        )

    def test_it_creates_session_when_creating_event(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp="2024-03-08",
        )

        response = sync_execute(
            """
            select
                *
            from sessions_v
            where
                distinct_id = %(distinct_id)s AND
                team_id = %(team_id)s
                """,
            {
                "distinct_id": distinct_id,
                "team_id": TEAM_ID,
            },
        )

        self.assertEqual(len(response), 1)

    def test_handles_different_distinct_id_across_same_session(self):
        distinct_id1 = create_distinct_id()
        distinct_id2 = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id1,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=TEAM,
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
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/entry", "$session_id": session_id},
            timestamp="2024-03-08:01",
        )
        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/middle", "$session_id": session_id},
            timestamp="2024-03-08:02",
        )
        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/middle", "$session_id": session_id},
            timestamp="2024-03-08:03",
        )
        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/exit", "$session_id": session_id},
            timestamp="2024-03-08:04",
        )

        responses = self.select_by_session_id(session_id)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["entry_url"], "/entry")
        self.assertEqual(responses[0]["exit_url"], "/exit")
        self.assertEqual(len(responses[0]["urls"]), 3)
        self.assertEqual(set(responses[0]["urls"]), {"/entry", "/middle", "/exit"})  # order is not guaranteed

    def test_handles_initial_utm_properties(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id, "utm_source": "source"},
            timestamp="2024-03-08",
        )
        _create_event(
            team=TEAM,
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
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=TEAM,
            event="$autocapture",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=TEAM,
            event="$autocapture",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=TEAM,
            event="other event",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=TEAM,
            event="$pageleave",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )

        responses = self.select_by_session_id(session_id)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["pageview_count"], 1)
        self.assertEqual(responses[0]["autocapture_count"], 2)
        self.assertEqual(
            responses[0]["event_count_map"], {"$pageview": 1, "$autocapture": 2, "other event": 1, "$pageleave": 1}
        )

    def test_separates_sessions_across_same_user(self):
        distinct_id = create_distinct_id()
        session_id1 = create_session_id()
        session_id2 = create_session_id()
        session_id3 = create_session_id()

        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id1},
            timestamp="2024-03-08",
        )
        _create_event(
            team=TEAM,
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
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )

        # we can't include all the columns as this clickhouse driver doesn't support selecting states
        responses = sync_execute(
            """
        SELECT
            session_id,
            team_id,
            distinct_id,
            min_timestamp,
            max_timestamp,
            urls,
            event_count_map,
            pageview_count,
            autocapture_count
        FROM sessions
        WHERE session_id = %(session_id)s AND team_id = %(team_id)s
        """,
            {
                "session_id": session_id,
                "team_id": TEAM_ID,
            },
        )
        self.assertEqual(len(responses), 1)

    def test_select_from_sessions_mv(self):
        # just make sure that we can select from the sessions mv without error
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=TEAM,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id},
            timestamp="2024-03-08",
        )

        # we can't include all the columns as this clickhouse driver doesn't support selecting states
        responses = sync_execute(
            """
        SELECT
            session_id,
            team_id,
            distinct_id,
            min_timestamp,
            max_timestamp,
            urls,
            event_count_map,
            pageview_count,
            autocapture_count
        FROM sessions_mv
        WHERE session_id = %(session_id)s AND team_id = %(team_id)s
        """,
            {
                "session_id": session_id,
                "team_id": TEAM_ID,
            },
        )
        self.assertEqual(len(responses), 1)
