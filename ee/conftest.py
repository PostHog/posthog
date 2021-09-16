import pytest
from infi.clickhouse_orm import Database

from ee.clickhouse.client import sync_execute
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
)
from posthog.test.base import TestMixin
from posthog.utils import is_clickhouse_enabled


def reset_clickhouse_tables():
    # Reset clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from ee.clickhouse.sql.cohort import CREATE_COHORTPEOPLE_TABLE_SQL, DROP_COHORTPEOPLE_TABLE_SQL
    from ee.clickhouse.sql.events import DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
    from ee.clickhouse.sql.person import (
        DROP_PERSON_DISTINCT_ID_TABLE_SQL,
        DROP_PERSON_STATIC_COHORT_TABLE_SQL,
        DROP_PERSON_TABLE_SQL,
        PERSON_STATIC_COHORT_TABLE_SQL,
        PERSONS_DISTINCT_ID_TABLE_SQL,
        PERSONS_TABLE_SQL,
    )
    from ee.clickhouse.sql.plugin_log_entries import DROP_PLUGIN_LOG_ENTRIES_TABLE_SQL, PLUGIN_LOG_ENTRIES_TABLE_SQL
    from ee.clickhouse.sql.session_recording_events import (
        DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
        SESSION_RECORDING_EVENTS_TABLE_SQL,
    )

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    TABLES_TO_CREATE_DROP = [
        (DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL),
        (DROP_PERSON_TABLE_SQL, PERSONS_TABLE_SQL),
        (DROP_PERSON_DISTINCT_ID_TABLE_SQL, PERSONS_DISTINCT_ID_TABLE_SQL),
        (DROP_PERSON_STATIC_COHORT_TABLE_SQL, PERSON_STATIC_COHORT_TABLE_SQL),
        (DROP_SESSION_RECORDING_EVENTS_TABLE_SQL, SESSION_RECORDING_EVENTS_TABLE_SQL),
        (DROP_PLUGIN_LOG_ENTRIES_TABLE_SQL, PLUGIN_LOG_ENTRIES_TABLE_SQL),
        (DROP_COHORTPEOPLE_TABLE_SQL, CREATE_COHORTPEOPLE_TABLE_SQL),
    ]
    for item in TABLES_TO_CREATE_DROP:
        try:
            sync_execute(item[0])
        except Exception as e:
            pass
        try:
            sync_execute(item[1])
        except Exception as e:
            pass


if is_clickhouse_enabled():

    @pytest.fixture(scope="package")
    def django_db_setup(django_db_setup, django_db_keepdb):
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            verify_ssl_cert=CLICKHOUSE_VERIFY,
        )

        if not django_db_keepdb:
            try:
                database.drop_database()
            except:
                pass

        if not django_db_keepdb or not database.db_exists:
            database.create_database()

        reset_clickhouse_tables()

        yield

        if not django_db_keepdb:
            try:
                database.drop_database()
            except:
                pass


@pytest.fixture
def base_test_mixin_fixture():
    kls = TestMixin()
    kls.setUp()
    kls.setUpTestData()

    return kls


@pytest.fixture
def team(base_test_mixin_fixture):
    return base_test_mixin_fixture.team
