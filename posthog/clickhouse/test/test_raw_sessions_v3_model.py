import datetime

from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.models.raw_sessions.sessions_v3 import (
    RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3,
    RAW_SESSION_TABLE_BACKFILL_SQL_V3,
)
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

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


@snapshot_clickhouse_queries
class TestRawSessionsModel(ClickhouseTestMixin, BaseTest):
    snapshot_replace_all_numbers = True

    def select_by_session_id(self, session_id):
        flush_persons_and_events()
        return query_with_columns(
            """
            select
                *
            from raw_sessions_v3_v
            where
                session_id_v7 = toUInt128(toUUID(%(session_id)s)) AND
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
            from raw_sessions_v3_v
            where
                session_id_v7 = toUInt128(toUUID(%(session_id)s))  AND
                team_id = %(team_id)s
                """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )

        assert len(response) == 1

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
        assert len(responses) == 1
        assert responses[0]["distinct_id"] in {distinct_id1, distinct_id2}
        assert responses[0]["pageview_uniq"] == 2

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
        assert len(responses) == 1
        assert responses[0]["entry_url"] == "/entry"
        assert responses[0]["end_url"] == "/exit"
        assert len(responses[0]["urls"]) == 3
        assert set(responses[0]["urls"]) == {"/entry", "/middle", "/exit"}  # order is not guaranteed

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
        assert len(responses) == 1
        assert responses[0]["entry_utm_source"] == "source"

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
        assert len(responses) == 1
        assert responses[0]["pageview_uniq"] == 1
        assert responses[0]["autocapture_uniq"] == 2

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
        assert len(responses) == 1
        responses = self.select_by_session_id(session_id2)
        assert len(responses) == 1
        responses = self.select_by_session_id(session_id3)
        assert len(responses) == 0

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
            urls
        FROM raw_sessions_v3
        WHERE session_id_v7 = toUInt128(toUUID(%(session_id)s)) AND team_id = %(team_id)s
        """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )
        assert len(responses) == 1

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
            urls
        FROM raw_sessions_v3_mv
        WHERE session_id_v7 = toUInt128(toUUID(%(session_id)s)) AND team_id = %(team_id)s
        """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )
        assert len(responses) == 1

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

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id=distinct_id,
            session_id=session_id,
            first_timestamp="2024-03-08",
            last_timestamp="2024-03-08",
        )

        # just test that the backfill SQL can be run without error
        sync_execute(
            RAW_SESSION_TABLE_BACKFILL_SQL_V3("team_id = %(team_id)s AND timestamp >= '2024-03-01'"),
            {"team_id": self.team.id},
        )
        sync_execute(
            RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3("team_id = %(team_id)s AND min_timestamp >= '2024-03-01'"),
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
        assert abs((max_inserted_at - now).total_seconds()) < 10

    def test_ad_ids_map_and_set(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        present_ad_id = "irclid"
        missing_ad_id = "wbraid"
        value = "test_irclid"

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$session_id": session_id, present_ad_id: value},
            timestamp="2024-03-08",
        )

        result = self.select_by_session_id(session_id)

        assert result[0]["entry_ad_ids_map"][present_ad_id] == value
        assert missing_ad_id not in result[0]["entry_ad_ids_map"].keys()

        assert present_ad_id in result[0]["entry_ad_ids_set"]
        assert missing_ad_id not in result[0]["entry_ad_ids_set"]

    def test_channel_type_properties(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={
                "$session_id": session_id,
                "gad_source": "1",
                "gclid": "some_gclid",
                "$referring_domain": "google.com",
                "utm_campaign": "some_campaign",
                "utm_medium": "some_medium",
                "utm_source": "some_source",
            },
            timestamp="2024-03-08",
        )

        result = self.select_by_session_id(session_id)

        assert result[0]["entry_channel_type_properties"] == (
            "some_source",
            "some_medium",
            "some_campaign",
            "google.com",
            True,
            False,
            "1",
        )

    def test_autocapture_does_not_set_attribution_when_pageview_present(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id=distinct_id,
            properties={
                "$session_id": session_id,
                "$current_url": "/1",
                "utm_source": "source1",
            },
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={
                "$session_id": session_id,
                "$current_url": "/2",
                "utm_source": "source2",
            },
            timestamp="2024-03-09",
        )

        result = self.select_by_session_id(session_id)

        assert result[0]["entry_url"] == "/2"
        assert result[0]["end_url"] == "/2"
        assert result[0]["urls"] == ["/2"]
        assert result[0]["entry_utm_source"] == "source2"

    def test_autocapture_does_set_attribution_when_only_event(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id=distinct_id,
            properties={
                "$session_id": session_id,
                "$current_url": "/1",
                "utm_source": "source1",
            },
            timestamp="2024-03-08",
        )

        result = self.select_by_session_id(session_id)

        assert result[0]["entry_url"] == "/1"
        assert result[0]["end_url"] == "/1"
        assert result[0]["urls"] == []
        assert result[0]["entry_utm_source"] == "source1"

    def test_store_all_feature_flag_values(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={
                "$session_id": session_id,
                "$feature/flag_string": "f1_a",
                "$feature/flag_int": 1,
                "$feature/flag_complex": ["hello", 123],
                "$feature/flag_duplicates": "a",
            },
            timestamp="2024-03-08",
        )

        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id=distinct_id,
            properties={
                "$session_id": session_id,
                "$feature/flag_string": "f1_b",
                "$feature/flag_int": 2,
                "$feature/flag_complex": {"key": "value"},
                "$feature/flag_duplicates": "a",
            },
            timestamp="2024-03-08",
        )

        result = self.select_by_session_id(session_id)

        # contains all values
        assert set(result[0]["flag_values"]["$feature/flag_string"]) == {"f1_a", "f1_b"}
        # converts to string
        assert set(result[0]["flag_values"]["$feature/flag_int"]) == {"1", "2"}
        # converts to json string
        assert set(result[0]["flag_values"]["$feature/flag_complex"]) == {'["hello",123]', '{"key":"value"}'}
        # deduplicates
        assert result[0]["flag_values"]["$feature/flag_duplicates"] == ["a"]

    def test_lookup_feature_flag(self):
        distinct_id_1 = create_distinct_id()
        session_id_1 = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id_1,
            properties={
                "$session_id": session_id_1,
                "$feature/flag_string": "f1_a",
            },
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="custom event",
            distinct_id=distinct_id_1,
            properties={
                "$session_id": session_id_1,
                "$feature/flag_string": "f1_b",
            },
            timestamp="2024-03-08",
        )

        distinct_id_2 = create_distinct_id()
        session_id_2 = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id_2,
            properties={
                "$session_id": session_id_2,
                "$feature/flag_string": "f1_c",
            },
            timestamp="2024-03-08",
        )

        result = query_with_columns(
            """
            select
                session_id_v7,
                has(flag_values['$feature/flag_string'], 'f1_a') as has_f1_a,
                has(flag_values['$feature/flag_string'], 'f1_b') as has_f1_b,
                has(flag_values['$feature/flag_string'], 'f1_c') as has_f1_c
            from raw_sessions_v3_v
            where
                team_id = %(team_id)s
            ORDER BY session_id_v7
                """,
            {
                "team_id": self.team.id,
            },
        )
        assert result[0]["has_f1_a"]
        assert result[0]["has_f1_b"]
        assert not result[0]["has_f1_c"]

        assert not result[1]["has_f1_a"]
        assert not result[1]["has_f1_b"]
        assert result[1]["has_f1_c"]

    def test_tracks_all_distinct_ids(self):
        distinct_id_1 = create_distinct_id()
        distinct_id_2 = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id_1,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp="2024-03-08",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id_2,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp="2024-03-08",
        )

        result = self.select_by_session_id(session_id)

        assert set(result[0]["distinct_ids"]) == {distinct_id_1, distinct_id_2}

    def test_has_replay_events(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp="2024-03-08",
        )

        result_1 = self.select_by_session_id(session_id)
        assert result_1[0]["has_replay_events"] is False

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id=distinct_id,
            session_id=session_id,
            first_timestamp="2024-03-08",
            last_timestamp="2024-03-08",
        )

        result_2 = self.select_by_session_id(session_id)
        assert result_2[0]["has_replay_events"] is True

        # everything else except for inserted_at should be the same
        assert {k: v for k, v in result_1[0].items() if k not in {"has_replay_events", "max_inserted_at"}} == {
            k: v for k, v in result_2[0].items() if k not in {"has_replay_events", "max_inserted_at"}
        }
