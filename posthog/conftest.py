from typing import Any

import pytest
from django.conf import settings
from infi.clickhouse_orm import Database

from posthog.client import sync_execute
from posthog.models.raw_sessions.sql import TRUNCATE_RAW_SESSIONS_TABLE_SQL
from posthog.test.base import PostHogTestCase, run_clickhouse_statement_in_parallel


def create_clickhouse_tables(num_tables: int):
    # Create clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from posthog.clickhouse.schema import (
        CREATE_DATA_QUERIES,
        CREATE_DICTIONARY_QUERIES,
        CREATE_DISTRIBUTED_TABLE_QUERIES,
        CREATE_MERGETREE_TABLE_QUERIES,
        CREATE_MV_TABLE_QUERIES,
        CREATE_VIEW_QUERIES,
        build_query,
    )

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    CREATE_TABLE_QUERIES: tuple[Any, ...] = CREATE_MERGETREE_TABLE_QUERIES + CREATE_DISTRIBUTED_TABLE_QUERIES

    # Check if all the tables have already been created
    if num_tables == len(CREATE_TABLE_QUERIES):
        return

    table_queries = list(map(build_query, CREATE_TABLE_QUERIES))
    run_clickhouse_statement_in_parallel(table_queries)

    mv_queries = list(map(build_query, CREATE_MV_TABLE_QUERIES))
    run_clickhouse_statement_in_parallel(mv_queries)

    view_queries = list(map(build_query, CREATE_VIEW_QUERIES))
    run_clickhouse_statement_in_parallel(view_queries)

    data_queries = list(map(build_query, CREATE_DATA_QUERIES))
    run_clickhouse_statement_in_parallel(data_queries)

    dictionary_queries = list(map(build_query, CREATE_DICTIONARY_QUERIES))
    run_clickhouse_statement_in_parallel(dictionary_queries)


def reset_clickhouse_tables():
    # Truncate clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from posthog.clickhouse.dead_letter_queue import (
        TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL,
    )
    from posthog.clickhouse.plugin_log_entries import (
        TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    )
    from posthog.heatmaps.sql import TRUNCATE_HEATMAPS_TABLE_SQL
    from posthog.models.app_metrics.sql import TRUNCATE_APP_METRICS_TABLE_SQL
    from posthog.models.channel_type.sql import TRUNCATE_CHANNEL_DEFINITION_TABLE_SQL
    from posthog.models.cohort.sql import TRUNCATE_COHORTPEOPLE_TABLE_SQL
    from posthog.models.event.sql import TRUNCATE_EVENTS_TABLE_SQL
    from posthog.models.group.sql import TRUNCATE_GROUPS_TABLE_SQL
    from posthog.models.performance.sql import TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL
    from posthog.models.person.sql import (
        TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
        TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
        TRUNCATE_PERSON_TABLE_SQL,
    )
    from posthog.models.sessions.sql import TRUNCATE_SESSIONS_TABLE_SQL
    from posthog.session_recordings.sql.session_recording_event_sql import (
        TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL,
    )

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    TABLES_TO_CREATE_DROP = [
        TRUNCATE_EVENTS_TABLE_SQL(),
        TRUNCATE_PERSON_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
        TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
        TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL(),
        TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL,
        TRUNCATE_COHORTPEOPLE_TABLE_SQL,
        TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL,
        TRUNCATE_GROUPS_TABLE_SQL,
        TRUNCATE_APP_METRICS_TABLE_SQL,
        TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL,
        TRUNCATE_CHANNEL_DEFINITION_TABLE_SQL,
        TRUNCATE_SESSIONS_TABLE_SQL(),
        TRUNCATE_RAW_SESSIONS_TABLE_SQL(),
        TRUNCATE_HEATMAPS_TABLE_SQL(),
    ]

    run_clickhouse_statement_in_parallel(TABLES_TO_CREATE_DROP)

    from posthog.clickhouse.schema import (
        CREATE_DATA_QUERIES,
    )

    run_clickhouse_statement_in_parallel(list(CREATE_DATA_QUERIES))


@pytest.fixture(scope="package")
def django_db_setup(django_db_setup, django_db_keepdb):
    database = Database(
        settings.CLICKHOUSE_DATABASE,
        db_url=settings.CLICKHOUSE_HTTP_URL,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        cluster=settings.CLICKHOUSE_CLUSTER,
        verify_ssl_cert=settings.CLICKHOUSE_VERIFY,
        randomize_replica_paths=True,
    )

    if not django_db_keepdb:
        try:
            database.drop_database()
        except:
            pass

    database.create_database()  # Create database if it doesn't exist
    table_count = sync_execute(
        "SELECT count() FROM system.tables WHERE database = %(database)s",
        {"database": settings.CLICKHOUSE_DATABASE},
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
    kls = PostHogTestCase()
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
