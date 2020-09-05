from ee.clickhouse.client import async_execute, sync_execute
from ee.clickhouse.sql.elements import (
    DROP_ELEMENTS_GROUP_TABLE_SQL,
    DROP_ELEMENTS_TABLE_SQL,
    ELEMENT_GROUP_TABLE_SQL,
    ELEMENTS_TABLE_SQL,
)
from ee.clickhouse.sql.events import (
    DROP_EVENTS_TABLE_SQL,
    DROP_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL,
    DROP_MAT_EVENTS_PROP_TABLE_SQL,
    DROP_MAT_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL,
    EVENTS_TABLE_SQL,
    EVENTS_WITH_PROPS_TABLE_SQL,
    MAT_EVENT_PROP_TABLE_SQL,
    MAT_EVENTS_WITH_PROPS_TABLE_SQL,
)
from ee.clickhouse.sql.person import (
    DROP_PERSON_DISTINCT_ID_TABLE_SQL,
    DROP_PERSON_TABLE_SQL,
    PERSONS_DISTINCT_ID_TABLE_SQL,
    PERSONS_TABLE_SQL,
)


class ClickhouseTestMixin:
    def tearDown(self):
        self._destroy_event_tables()
        sync_execute(DROP_ELEMENTS_TABLE_SQL)
        sync_execute(DROP_ELEMENTS_GROUP_TABLE_SQL)
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(DROP_PERSON_DISTINCT_ID_TABLE_SQL)

        self._create_event_tables()
        sync_execute(ELEMENTS_TABLE_SQL)
        sync_execute(ELEMENT_GROUP_TABLE_SQL)
        sync_execute(PERSONS_TABLE_SQL)
        sync_execute(PERSONS_DISTINCT_ID_TABLE_SQL)

    def _destroy_event_tables(self):
        sync_execute(DROP_EVENTS_TABLE_SQL)
        sync_execute(DROP_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL)
        sync_execute(DROP_MAT_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL)
        sync_execute(DROP_MAT_EVENTS_PROP_TABLE_SQL)

    def _create_event_tables(self):
        sync_execute(EVENTS_TABLE_SQL)
        sync_execute(EVENTS_WITH_PROPS_TABLE_SQL)
        sync_execute(MAT_EVENTS_WITH_PROPS_TABLE_SQL)
        sync_execute(MAT_EVENT_PROP_TABLE_SQL)
