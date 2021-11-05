import pytest
from django.db import connection
from django.db.utils import ProgrammingError
from infi.clickhouse_orm import Database

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.dead_letter_queue import (
    DEAD_LETTER_QUEUE_TABLE_MV_SQL,
    DROP_DEAD_LETTER_QUEUE_TABLE_MV_SQL,
    DROP_KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
    KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
)
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
)
from posthog.test.base import TestMixin
from posthog.utils import is_clickhouse_enabled


def reset_clickhouse_tables(num_migrated_tables: int = 0):
    # Reset clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from ee.clickhouse.sql.cohort import CREATE_COHORTPEOPLE_TABLE_SQL, DROP_COHORTPEOPLE_TABLE_SQL
    from ee.clickhouse.sql.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE_SQL, DROP_DEAD_LETTER_QUEUE_TABLE_SQL
    from ee.clickhouse.sql.events import DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
    from ee.clickhouse.sql.groups import DROP_GROUPS_TABLE_SQL, GROUPS_TABLE_SQL
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
        (DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL, "events"),
        (DROP_PERSON_TABLE_SQL, PERSONS_TABLE_SQL, "persons"),
        (DROP_PERSON_DISTINCT_ID_TABLE_SQL, PERSONS_DISTINCT_ID_TABLE_SQL, "person_distinct_ids"),
        (DROP_PERSON_STATIC_COHORT_TABLE_SQL, PERSON_STATIC_COHORT_TABLE_SQL, "person_static_cohort"),
        (DROP_SESSION_RECORDING_EVENTS_TABLE_SQL, SESSION_RECORDING_EVENTS_TABLE_SQL, "session_recording"),
        (DROP_PLUGIN_LOG_ENTRIES_TABLE_SQL, PLUGIN_LOG_ENTRIES_TABLE_SQL, "plugin_log"),
        (DROP_COHORTPEOPLE_TABLE_SQL, CREATE_COHORTPEOPLE_TABLE_SQL, "cohortpeople"),
        (DROP_KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL, KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL, "kafka_dead_letter_queue"),
        (DROP_DEAD_LETTER_QUEUE_TABLE_SQL, DEAD_LETTER_QUEUE_TABLE_SQL, "dead_letter_queue"),
        (DROP_DEAD_LETTER_QUEUE_TABLE_MV_SQL, DEAD_LETTER_QUEUE_TABLE_MV_SQL, "dead_letter_queue_mv"),
        (DROP_GROUPS_TABLE_SQL, GROUPS_TABLE_SQL, "groups"),
    ]

    if num_migrated_tables == len(TABLES_TO_CREATE_DROP):
        return

    with connection.cursor() as cursor:
        for item in TABLES_TO_CREATE_DROP:
            sync_execute(item[0])
            sync_execute(item[1])
            cursor.execute("""INSERT INTO clickhouse_migrations (name) VALUES (%s);""", [item[2]])


if is_clickhouse_enabled():

    @pytest.fixture(scope="package")
    def django_db_setup(django_db_setup, django_db_blocker, django_db_keepdb):
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

        num_migrated_tables = 0

        with django_db_blocker.unblock():
            with connection.cursor() as cursor:
                try:
                    cursor.execute("SELECT * FROM clickhouse_migrations;")
                    result = cursor.fetchall()
                    num_migrated_tables = len(result)
                except ProgrammingError:

                    cursor.execute(
                        """CREATE TABLE clickhouse_migrations (
                            id SERIAL,
                            name varchar,
                            applied TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        )"""
                    )

            reset_clickhouse_tables(num_migrated_tables)

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


# :TRICKY: Integrate syrupy with unittest test cases
@pytest.fixture
def unittest_snapshot(request, snapshot):
    request.cls.snapshot = snapshot
