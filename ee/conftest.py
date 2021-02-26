import pytest
from infi.clickhouse_orm import Database

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import Person
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
)
from posthog.test.base import TestMixin


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

    database.migrate("ee.clickhouse.migrations")
    # Make DELETE / UPDATE synchronous to avoid flaky tests
    sync_execute("SET mutations_sync = 1")

    yield

    if not django_db_keepdb:
        try:
            database.drop_database()
        except:
            pass


@pytest.fixture
def db(db):
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

    yield

    try:
        sync_execute(DROP_EVENTS_TABLE_SQL)
        sync_execute(DROP_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL)
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(DROP_PERSON_DISTINCT_ID_TABLE_SQL)
        sync_execute(DROP_PERSON_STATIC_COHORT_TABLE_SQL)
        sync_execute(DROP_SESSION_RECORDING_EVENTS_TABLE_SQL)

        sync_execute(EVENTS_TABLE_SQL)
        sync_execute(EVENTS_WITH_PROPS_TABLE_SQL)
        sync_execute(SESSION_RECORDING_EVENTS_TABLE_SQL)
        sync_execute(PERSONS_TABLE_SQL)
        sync_execute(PERSONS_DISTINCT_ID_TABLE_SQL)
        sync_execute(PERSON_STATIC_COHORT_TABLE_SQL)
    except:
        pass


@pytest.fixture
def base_test_mixin_fixture():
    kls = TestMixin()
    kls.setUp()

    return kls


@pytest.fixture
def team(base_test_mixin_fixture):
    return base_test_mixin_fixture.team
