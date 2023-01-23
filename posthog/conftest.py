import pytest
from django.conf import settings
from infi.clickhouse_orm import Database

from posthog.clickhouse.schema import (
    CREATE_DISTRIBUTED_TABLE_QUERIES,
    CREATE_KAFKA_TABLE_QUERIES,
    CREATE_MERGETREE_TABLE_QUERIES,
    CREATE_MV_TABLE_QUERIES,
)
from posthog.management.commands.setup_test_environment import create_clickhouse_schema_in_parallel
from posthog.test.base import TestMixin, run_clickhouse_statement_in_parallel


def create_clickhouse_tables_quickly():
    # Create ClickHouse tables using their CREATE SQL statements rather than
    # running through the ClickHouse migrations, which is slow. Primarily used
    # to make test setup fast.
    create_clickhouse_schema_in_parallel(CREATE_MERGETREE_TABLE_QUERIES)
    create_clickhouse_schema_in_parallel(CREATE_KAFKA_TABLE_QUERIES)
    create_clickhouse_schema_in_parallel(CREATE_DISTRIBUTED_TABLE_QUERIES)
    create_clickhouse_schema_in_parallel(CREATE_MV_TABLE_QUERIES)


def reset_clickhouse_tables():
    # Truncate clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from posthog.clickhouse.dead_letter_queue import TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL
    from posthog.clickhouse.plugin_log_entries import TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL
    from posthog.models.app_metrics.sql import TRUNCATE_APP_METRICS_TABLE_SQL
    from posthog.models.cohort.sql import TRUNCATE_COHORTPEOPLE_TABLE_SQL
    from posthog.models.event.sql import TRUNCATE_EVENTS_TABLE_SQL
    from posthog.models.group.sql import TRUNCATE_GROUPS_TABLE_SQL
    from posthog.models.performance.sql import TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL
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
        TRUNCATE_GROUPS_TABLE_SQL,
        TRUNCATE_APP_METRICS_TABLE_SQL,
        TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL,
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
    create_clickhouse_tables_quickly()

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


@pytest.fixture
def user(base_test_mixin_fixture):
    return base_test_mixin_fixture.user


# :TRICKY: Integrate syrupy with unittest test cases
@pytest.fixture
def unittest_snapshot(request, snapshot):
    request.cls.snapshot = snapshot


@pytest.fixture
def cache():
    from django.core.cache import cache as django_cache

    django_cache.clear()

    yield django_cache

    django_cache.clear()
