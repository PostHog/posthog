from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog import settings
from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.models.raw_sessions.sessions_on_events_overrides import (
    RAW_SESSION_OVERRIDES_EVENTS_VIEW_NAME_V3,
    SESSION_OVERRIDES_SNAPSHOT_TABLE_V3_CREATE_SQL,
    SESSION_OVERRIDES_SNAPSHOT_TABLE_V3_POPULATE_SQL,
    SESSION_OVERRIDES_SNAPSHOT_UPDATE_SQL,
    SESSIONS_OVERRIDES_DICT_V3_CREATE_SQL,
)
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


class TestSessionsOnEventsModel(ClickhouseTestMixin, BaseTest):
    snapshot_replace_all_numbers = True

    def tearDown(self):
        sync_execute(f"DROP DICTIONARY IF EXISTS {self.get_temp_dict_name()}")
        sync_execute(f"DROP TABLE IF EXISTS {self.get_temp_table_name()} SYNC")
        super().tearDown()

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

    def get_temp_table_name(self):
        return f"test_session_overrides_table_{self.team.id}"

    def get_temp_dict_name(self):
        return f"{self.get_temp_table_name()}_dict"

    def create_test_event(self, distinct_id, session_id, timestamp="2024-03-08"):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp=timestamp,
        )

    def create_snapshot_table(self):
        create_table = SESSION_OVERRIDES_SNAPSHOT_TABLE_V3_CREATE_SQL(self.get_temp_table_name())
        sync_execute(create_table)

    def populate_snapshot_table(self, squash_timestamp=None):
        if not squash_timestamp:
            # pick a default squash timestamp in the future
            squash_timestamp = datetime.now() + timedelta(days=7)
        populate_table = SESSION_OVERRIDES_SNAPSHOT_TABLE_V3_POPULATE_SQL(self.get_temp_table_name())
        sync_execute(
            populate_table,
            args={
                "timestamp": squash_timestamp.isoformat(),
            },
        )

    def create_snapshot_dict(self):
        create_dict = SESSIONS_OVERRIDES_DICT_V3_CREATE_SQL(
            self.get_temp_dict_name(), shards=1, max_execution_time=0, max_memory_usage=0
        )

        sync_execute(
            create_dict,
            {
                "table": self.get_temp_table_name(),
                "user": settings.CLICKHOUSE_USER,
                "password": settings.CLICKHOUSE_PASSWORD,
            },
        )

    def update_events_from_dict(self):
        update = SESSION_OVERRIDES_SNAPSHOT_UPDATE_SQL()
        sync_execute(update, args={"dict_name": self.get_temp_dict_name()})

    def test_it_creates_session_overrides_entry_when_creating_event(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        self.create_test_event(distinct_id, session_id)

        response = sync_execute(
            """
            select
                session_id_v7,
                team_id
            from raw_sessions_overrides_v3
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

    def test_it_creates_the_temp_table(self):
        self.create_snapshot_table()

    def test_it_creates_and_populates_the_temp_table(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        self.create_test_event(distinct_id, session_id)
        self.create_snapshot_table()
        self.populate_snapshot_table()

        response = sync_execute(
            f"""
            select
                count()
            from {self.get_temp_table_name()}
            where
                session_id_v7 = toUInt128(toUUID(%(session_id)s)) AND
                team_id = %(team_id)s
                """,
            {
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )

        assert len(response) == 1

    def test_it_updates_the_events_table_using_a_dict(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        self.create_test_event(distinct_id, session_id)
        self.create_snapshot_table()
        self.populate_snapshot_table()
        self.create_snapshot_dict()
        self.update_events_from_dict()

        response = sync_execute(
            """
            SELECT
                soe_min_timestamp,
                soe_entry_url
            FROM events
            WHERE
                `$session_id_uuid` = toUInt128(toUUID(%(session_id)s)) AND
                team_id = %(team_id)s
                """,
            args={
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )

        assert len(response) == 1
        assert response[0][0] is not None
        assert response[0][1] == "/"

    def test_squashing_does_not_change_joined_results(self):
        distinct_id = create_distinct_id()
        session_id = create_session_id()
        self.create_test_event(distinct_id, session_id)

        response = sync_execute(
            f"""
            SELECT
                soe_min_timestamp,
                soe_entry_url
            FROM {RAW_SESSION_OVERRIDES_EVENTS_VIEW_NAME_V3}
            WHERE
                `$session_id_uuid` = toUInt128(toUUID(%(session_id)s)) AND
                team_id = %(team_id)s
                """,
            args={
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )

        assert len(response) == 1
        assert response[0][0] is not None
        assert response[0][1] == "/"

        self.create_snapshot_table()
        self.populate_snapshot_table()
        self.create_snapshot_dict()
        self.update_events_from_dict()

        response = sync_execute(
            f"""
            SELECT
                soe_min_timestamp,
                soe_entry_url
            FROM {RAW_SESSION_OVERRIDES_EVENTS_VIEW_NAME_V3}
            WHERE
                `$session_id_uuid` = toUInt128(toUUID(%(session_id)s)) AND
                team_id = %(team_id)s
                """,
            args={
                "session_id": session_id,
                "team_id": self.team.id,
            },
        )

        assert len(response) == 1
        assert response[0][0] is not None
        assert response[0][1] == "/"
