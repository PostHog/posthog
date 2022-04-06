import pytest
from django.conf import settings
from infi.clickhouse_orm import Database

from ee.clickhouse.sql.dead_letter_queue import (
    DEAD_LETTER_QUEUE_TABLE_MV_SQL,
    KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
    TRUNCATE_DEAD_LETTER_QUEUE_TABLE_MV_SQL,
)
from posthog.client import sync_execute
from posthog.test.base import TestMixin


def create_clickhouse_tables(num_tables: int):
    # Reset clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from ee.clickhouse.sql.cohort import CREATE_COHORTPEOPLE_TABLE_SQL
    from ee.clickhouse.sql.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE_SQL
    from ee.clickhouse.sql.events import DISTRIBUTED_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL, WRITABLE_EVENTS_TABLE_SQL
    from ee.clickhouse.sql.groups import GROUPS_TABLE_SQL
    from ee.clickhouse.sql.person import (
        PERSON_DISTINCT_ID2_TABLE_SQL,
        PERSON_STATIC_COHORT_TABLE_SQL,
        PERSONS_DISTINCT_ID_TABLE_SQL,
        PERSONS_TABLE_SQL,
    )
    from ee.clickhouse.sql.plugin_log_entries import PLUGIN_LOG_ENTRIES_TABLE_SQL
    from ee.clickhouse.sql.session_recording_events import (
        DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
        SESSION_RECORDING_EVENTS_TABLE_SQL,
        WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
    )

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    TABLES_TO_CREATE_DROP = [
        EVENTS_TABLE_SQL(),
        PERSONS_TABLE_SQL(),
        PERSONS_DISTINCT_ID_TABLE_SQL(),
        PERSON_DISTINCT_ID2_TABLE_SQL(),
        PERSON_STATIC_COHORT_TABLE_SQL(),
        SESSION_RECORDING_EVENTS_TABLE_SQL(),
        PLUGIN_LOG_ENTRIES_TABLE_SQL(),
        CREATE_COHORTPEOPLE_TABLE_SQL(),
        KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL(),
        DEAD_LETTER_QUEUE_TABLE_SQL(),
        DEAD_LETTER_QUEUE_TABLE_MV_SQL,
        GROUPS_TABLE_SQL(),
    ]

    if settings.CLICKHOUSE_REPLICATION:
        TABLES_TO_CREATE_DROP.extend(
            [
                DISTRIBUTED_EVENTS_TABLE_SQL(),
                WRITABLE_EVENTS_TABLE_SQL(),
                DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL(),
            ]
        )

    if num_tables == len(TABLES_TO_CREATE_DROP):
        return

    for item in TABLES_TO_CREATE_DROP:
        sync_execute(item)


def reset_clickhouse_tables():
    # Reset clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from ee.clickhouse.sql.cohort import TRUNCATE_COHORTPEOPLE_TABLE_SQL
    from ee.clickhouse.sql.dead_letter_queue import TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL
    from ee.clickhouse.sql.events import TRUNCATE_EVENTS_TABLE_SQL
    from ee.clickhouse.sql.groups import TRUNCATE_GROUPS_TABLE_SQL
    from ee.clickhouse.sql.person import (
        TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
        TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
        TRUNCATE_PERSON_TABLE_SQL,
    )
    from ee.clickhouse.sql.plugin_log_entries import TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL
    from ee.clickhouse.sql.session_recording_events import TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    TABLES_TO_CREATE_DROP = [
        TRUNCATE_EVENTS_TABLE_SQL(),
        TRUNCATE_PERSON_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
        TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
        TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL(),
        TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL,
        TRUNCATE_COHORTPEOPLE_TABLE_SQL,
        TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL,
        TRUNCATE_DEAD_LETTER_QUEUE_TABLE_MV_SQL,
        TRUNCATE_GROUPS_TABLE_SQL,
    ]

    for item in TABLES_TO_CREATE_DROP:
        sync_execute(item)


@pytest.fixture(scope="package")
def django_db_setup(django_db_setup, django_db_keepdb):
    database = Database(
        settings.CLICKHOUSE_DATABASE,
        db_url=settings.CLICKHOUSE_HTTP_URL,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        cluster=settings.CLICKHOUSE_CLUSTER,
        verify_ssl_cert=settings.CLICKHOUSE_VERIFY,
    )

    if not django_db_keepdb:
        try:
            database.drop_database()
        except:
            pass

    database.create_database()  # Create database if it doesn't exist
    table_count = sync_execute(
        "SELECT count() FROM system.tables WHERE database = %(database)s", {"database": settings.CLICKHOUSE_DATABASE}
    )[0][0]
    create_clickhouse_tables(table_count)

    yield

    if django_db_keepdb:
        reset_clickhouse_tables()
    else:
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


# :TRICKY: Integrate syrupy with unittest test cases
@pytest.fixture
def unittest_snapshot(request, snapshot):
    request.cls.snapshot = snapshot
