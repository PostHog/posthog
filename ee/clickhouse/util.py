from contextlib import contextmanager

from clickhouse_driver.errors import ServerException
from django.db import DEFAULT_DB_ALIAS

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import (
    DROP_EVENTS_TABLE_SQL,
    DROP_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL,
    EVENTS_TABLE_SQL,
    EVENTS_WITH_PROPS_TABLE_SQL,
)
from ee.clickhouse.sql.person import (
    DROP_PERSON_DISTINCT_ID_TABLE_SQL,
    DROP_PERSON_STATIC_COHORT_TABLE_SQL,
    DROP_PERSON_TABLE_SQL,
    PERSON_STATIC_COHORT_TABLE_SQL,
    PERSONS_DISTINCT_ID_TABLE_SQL,
    PERSONS_TABLE_SQL,
)
from ee.clickhouse.sql.session_recording_events import (
    DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
)


class ClickhouseTestMixin:
    def tearDown(self):
        try:
            self._destroy_event_tables()
            self._destroy_person_tables()
            self._destroy_session_recording_tables()

            self._create_event_tables()
            self._create_person_tables()
            self._create_session_recording_tables()
        except ServerException as e:
            print(e)
            pass

    def _destroy_person_tables(self):
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(DROP_PERSON_DISTINCT_ID_TABLE_SQL)
        sync_execute(DROP_PERSON_STATIC_COHORT_TABLE_SQL)

    def _create_person_tables(self):
        sync_execute(PERSONS_TABLE_SQL)
        sync_execute(PERSONS_DISTINCT_ID_TABLE_SQL)
        sync_execute(PERSON_STATIC_COHORT_TABLE_SQL)

    def _destroy_session_recording_tables(self):
        sync_execute(DROP_SESSION_RECORDING_EVENTS_TABLE_SQL)

    def _create_session_recording_tables(self):
        sync_execute(SESSION_RECORDING_EVENTS_TABLE_SQL)

    def _destroy_event_tables(self):
        sync_execute(DROP_EVENTS_TABLE_SQL)
        sync_execute(DROP_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL)

    def _create_event_tables(self):
        sync_execute(EVENTS_TABLE_SQL)
        sync_execute(EVENTS_WITH_PROPS_TABLE_SQL)

    @contextmanager
    def _assertNumQueries(self, func):
        yield

    # Ignore assertNumQueries in clickhouse tests
    def assertNumQueries(self, num, func=None, *args, using=DEFAULT_DB_ALIAS, **kwargs):
        return self._assertNumQueries(func)
