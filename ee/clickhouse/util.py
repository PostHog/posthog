import posthoganalytics
from django.conf import settings

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.elements import DROP_ELEMENTS_TABLE_SQL, ELEMENTS_TABLE_SQL
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
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(DROP_PERSON_DISTINCT_ID_TABLE_SQL)

        self._create_event_tables()
        sync_execute(ELEMENTS_TABLE_SQL)
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


CH_PERSON_ENDPOINT = "ch-person-endpoint"
CH_EVENT_ENDPOINT = "ch-event-endpoint"
CH_ACTION_ENDPOINT = "ch-action-endpoint"
CH_TREND_ENDPOINT = "ch-trend-endpoint"
CH_SESSION_ENDPOINT = "ch-session-endpoint"
CH_PATH_ENDPOINT = "ch-path-endpoint"
CH_FUNNEL_ENDPOINT = "ch-funnel-endpoint"
CH_RETENTION_ENDPOINT = "ch-retention-endpoint"


def endpoint_enabled(endpoint_flag: str, distinct_id: str):
    return posthoganalytics.feature_enabled(endpoint_flag, distinct_id) or settings.DEBUG or settings.TEST
