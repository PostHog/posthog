import pytest
from django.conf import settings
from infi.clickhouse_orm import Database

from posthog.client import sync_execute
from posthog.test.base import TestMixin, run_clickhouse_statement_in_parallel


def create_clickhouse_tables(num_tables: int):
    # Reset clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from ee.clickhouse.sql.groups import GROUPS_TABLE_SQL
    from posthog.clickhouse.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE_MV_SQL, DEAD_LETTER_QUEUE_TABLE_SQL
    from posthog.clickhouse.plugin_log_entries import PLUGIN_LOG_ENTRIES_TABLE_SQL
    from posthog.models.cohort.sql import CREATE_COHORTPEOPLE_TABLE_SQL
    from posthog.models.event.sql import DISTRIBUTED_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL, WRITABLE_EVENTS_TABLE_SQL
    from posthog.models.person.sql import (
        PERSON_DISTINCT_ID2_TABLE_SQL,
        PERSON_STATIC_COHORT_TABLE_SQL,
        PERSONS_DISTINCT_ID_TABLE_SQL,
        PERSONS_TABLE_SQL,
    )
    from posthog.models.session_recording_event.sql import (
        DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
        SESSION_RECORDING_EVENTS_TABLE_SQL,
        WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
    )

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    FIRST_BATCH_OF_TABLES_TO_CREATE_DROP = [
        EVENTS_TABLE_SQL(),
        PERSONS_TABLE_SQL(),
        PERSONS_DISTINCT_ID_TABLE_SQL(),
        PERSON_DISTINCT_ID2_TABLE_SQL(),
        PERSON_STATIC_COHORT_TABLE_SQL(),
        SESSION_RECORDING_EVENTS_TABLE_SQL(),
        PLUGIN_LOG_ENTRIES_TABLE_SQL(),
        CREATE_COHORTPEOPLE_TABLE_SQL(),
        DEAD_LETTER_QUEUE_TABLE_SQL(),
        GROUPS_TABLE_SQL(),
    ]

    if settings.CLICKHOUSE_REPLICATION:
        FIRST_BATCH_OF_TABLES_TO_CREATE_DROP.extend(
            [
                DISTRIBUTED_EVENTS_TABLE_SQL(),
                WRITABLE_EVENTS_TABLE_SQL(),
                DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL(),
            ]
        )

    # Because the tables are created in parallel, any tables that depend on another
    # table should be created in a second batch - to ensure the first table already
    # exists. Tables for this second batch of table creation are defined here:
    SECOND_BATCH_OF_TABLES_TO_CREATE_DROP = [DEAD_LETTER_QUEUE_TABLE_MV_SQL]

    # Check if all the tables have already been created
    if num_tables == len(FIRST_BATCH_OF_TABLES_TO_CREATE_DROP + SECOND_BATCH_OF_TABLES_TO_CREATE_DROP):
        return

    run_clickhouse_statement_in_parallel(FIRST_BATCH_OF_TABLES_TO_CREATE_DROP)
    run_clickhouse_statement_in_parallel(SECOND_BATCH_OF_TABLES_TO_CREATE_DROP)


def reset_clickhouse_tables():
    # Reset clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from ee.clickhouse.sql.groups import TRUNCATE_GROUPS_TABLE_SQL
    from posthog.clickhouse.dead_letter_queue import (
        TRUNCATE_DEAD_LETTER_QUEUE_TABLE_MV_SQL,
        TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL,
    )
    from posthog.clickhouse.plugin_log_entries import TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL
    from posthog.models.cohort.sql import TRUNCATE_COHORTPEOPLE_TABLE_SQL
    from posthog.models.event.sql import TRUNCATE_EVENTS_TABLE_SQL
    from posthog.models.person.sql import (
        TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
        TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
        TRUNCATE_PERSON_TABLE_SQL,
    )
    from posthog.models.session_recording_event.sql import TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL

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

    run_clickhouse_statement_in_parallel(TABLES_TO_CREATE_DROP)


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
