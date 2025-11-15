import os
import subprocess
from urllib.parse import quote_plus

import pytest
from posthog.test.base import PostHogTestCase, run_clickhouse_statement_in_parallel

from django.conf import settings

from infi.clickhouse_orm import Database

from posthog.clickhouse.client import sync_execute


def create_clickhouse_tables():
    # Create clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from posthog.clickhouse.schema import (
        CREATE_DATA_QUERIES,
        CREATE_DICTIONARY_QUERIES,
        CREATE_DISTRIBUTED_TABLE_QUERIES,
        CREATE_KAFKA_TABLE_QUERIES,
        CREATE_MERGETREE_TABLE_QUERIES,
        CREATE_MV_TABLE_QUERIES,
        CREATE_VIEW_QUERIES,
        build_query,
    )

    num_expected_tables = (
        len(CREATE_MERGETREE_TABLE_QUERIES)
        + len(CREATE_DISTRIBUTED_TABLE_QUERIES)
        + len(CREATE_MV_TABLE_QUERIES)
        + len(CREATE_VIEW_QUERIES)
        + len(CREATE_DICTIONARY_QUERIES)
    )

    # Evaluation tests use Kafka for faster data ingestion.
    if settings.IN_EVAL_TESTING:
        num_expected_tables += len(CREATE_KAFKA_TABLE_QUERIES)

    [[num_tables]] = sync_execute(
        "SELECT count() FROM system.tables WHERE database = %(database)s",
        {"database": settings.CLICKHOUSE_DATABASE},
    )

    # Check if all the tables have already been created. Views, materialized views, and dictionaries also count
    if num_tables == num_expected_tables:
        return

    table_queries = list(map(build_query, CREATE_MERGETREE_TABLE_QUERIES + CREATE_DISTRIBUTED_TABLE_QUERIES))
    run_clickhouse_statement_in_parallel(table_queries)

    if settings.IN_EVAL_TESTING:
        kafka_table_queries = list(map(build_query, CREATE_KAFKA_TABLE_QUERIES))
        run_clickhouse_statement_in_parallel(kafka_table_queries)

    mv_queries = list(map(build_query, CREATE_MV_TABLE_QUERIES))
    run_clickhouse_statement_in_parallel(mv_queries)

    view_queries = list(map(build_query, CREATE_VIEW_QUERIES))
    run_clickhouse_statement_in_parallel(view_queries)

    dictionary_queries = list(map(build_query, CREATE_DICTIONARY_QUERIES))
    run_clickhouse_statement_in_parallel(dictionary_queries)

    data_queries = list(map(build_query, CREATE_DATA_QUERIES))
    run_clickhouse_statement_in_parallel(data_queries)


def reset_clickhouse_tables():
    # Truncate clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from posthog.clickhouse.dead_letter_queue import TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL
    from posthog.clickhouse.plugin_log_entries import TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL
    from posthog.heatmaps.sql import TRUNCATE_HEATMAPS_TABLE_SQL
    from posthog.models.ai.pg_embeddings import TRUNCATE_PG_EMBEDDINGS_TABLE_SQL
    from posthog.models.app_metrics.sql import TRUNCATE_APP_METRICS_TABLE_SQL
    from posthog.models.channel_type.sql import TRUNCATE_CHANNEL_DEFINITION_TABLE_SQL
    from posthog.models.cohort.sql import TRUNCATE_COHORTPEOPLE_TABLE_SQL
    from posthog.models.event.sql import TRUNCATE_EVENTS_RECENT_TABLE_SQL, TRUNCATE_EVENTS_TABLE_SQL
    from posthog.models.exchange_rate.sql import TRUNCATE_EXCHANGE_RATE_TABLE_SQL
    from posthog.models.group.sql import TRUNCATE_GROUPS_TABLE_SQL
    from posthog.models.performance.sql import TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL
    from posthog.models.person.sql import (
        TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
        TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
        TRUNCATE_PERSON_TABLE_SQL,
    )
    from posthog.models.raw_sessions.sessions_v2 import TRUNCATE_RAW_SESSIONS_TABLE_SQL
    from posthog.models.raw_sessions.sessions_v3 import TRUNCATE_RAW_SESSIONS_TABLE_SQL_V3
    from posthog.models.sessions.sql import TRUNCATE_SESSIONS_TABLE_SQL
    from posthog.session_recordings.sql.session_recording_event_sql import TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL

    from products.error_tracking.backend.embedding import TRUNCATE_DOCUMENT_EMBEDDINGS_TABLE_SQL
    from products.error_tracking.backend.sql import (
        TRUNCATE_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL,
        TRUNCATE_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL,
    )

    # REMEMBER TO ADD ANY NEW CLICKHOUSE TABLES TO THIS ARRAY!
    TABLES_TO_CREATE_DROP: list[str] = [
        TRUNCATE_EVENTS_TABLE_SQL(),
        TRUNCATE_EVENTS_RECENT_TABLE_SQL(),
        TRUNCATE_PERSON_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
        TRUNCATE_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL(),
        TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL(),
        TRUNCATE_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL(),
        TRUNCATE_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL(),
        TRUNCATE_DOCUMENT_EMBEDDINGS_TABLE_SQL(),
        TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL(),
        TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL,
        TRUNCATE_COHORTPEOPLE_TABLE_SQL,
        TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL,
        TRUNCATE_GROUPS_TABLE_SQL,
        TRUNCATE_APP_METRICS_TABLE_SQL,
        TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL,
        TRUNCATE_CHANNEL_DEFINITION_TABLE_SQL,
        TRUNCATE_EXCHANGE_RATE_TABLE_SQL(),
        TRUNCATE_SESSIONS_TABLE_SQL(),
        TRUNCATE_RAW_SESSIONS_TABLE_SQL_V3(),
        TRUNCATE_RAW_SESSIONS_TABLE_SQL(),
        TRUNCATE_HEATMAPS_TABLE_SQL(),
        TRUNCATE_PG_EMBEDDINGS_TABLE_SQL(),
    ]

    # Drop created Kafka tables because some tests don't expect it.
    if settings.IN_EVAL_TESTING:
        kafka_tables = sync_execute(
            f"""
            SELECT name
            FROM system.tables
            WHERE database = '{settings.CLICKHOUSE_DATABASE}' AND name LIKE 'kafka_%'
            """,
        )
        # Using `ON CLUSTER` takes x20 more time to drop the tables: https://github.com/ClickHouse/ClickHouse/issues/15473.
        TABLES_TO_CREATE_DROP += [f"DROP TABLE {table[0]}" for table in kafka_tables]

    run_clickhouse_statement_in_parallel(TABLES_TO_CREATE_DROP)

    from posthog.clickhouse.schema import CREATE_DATA_QUERIES

    run_clickhouse_statement_in_parallel(list(CREATE_DATA_QUERIES))


def create_persons_tables():
    """Create person/cohort/group tables using sqlx migrations.

    Drops any Django-created tables first, then runs sqlx migrations to create
    tables with correct schema. Runs once at test session start, parallel to ClickHouse setup.

    No transaction handling needed - matches ClickHouse pattern which just executes statements directly.
    """
    from django.db import connection

    # Drop Django-created tables and clear sqlx migration tracking
    with connection.cursor() as cursor:
        cursor.execute("""
            DROP TABLE IF EXISTS posthog_person CASCADE;
            DROP TABLE IF EXISTS posthog_person_new CASCADE;
            DROP TABLE IF EXISTS posthog_persondistinctid CASCADE;
            DROP TABLE IF EXISTS posthog_personlessdistinctid CASCADE;
            DROP TABLE IF EXISTS posthog_personoverridemapping CASCADE;
            DROP TABLE IF EXISTS posthog_personoverride CASCADE;
            DROP TABLE IF EXISTS posthog_pendingpersonoverride CASCADE;
            DROP TABLE IF EXISTS posthog_flatpersonoverride CASCADE;
            DROP TABLE IF EXISTS posthog_featureflaghashkeyoverride CASCADE;
            DROP TABLE IF EXISTS posthog_cohortpeople CASCADE;
            DROP TABLE IF EXISTS posthog_group CASCADE;
            DROP TABLE IF EXISTS posthog_grouptypemapping CASCADE;

            -- Clear sqlx migration tracking so sqlx recreates dropped tables
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_tables WHERE tablename = '_sqlx_migrations') THEN
                    DELETE FROM _sqlx_migrations;
                END IF;
            END $$;
        """)

    # Run sqlx migrations to create tables
    run_persons_sqlx_migrations()

    # Set sequence defaults for posthog_person_new
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE SEQUENCE IF NOT EXISTS posthog_person_new_id_seq START WITH 1000000000;
            ALTER TABLE posthog_person_new ALTER COLUMN id SET DEFAULT nextval('posthog_person_new_id_seq');
        """)


def reset_persons_tables():
    """Truncate person/cohort/group tables between test runs.

    Similar to reset_clickhouse_tables(), this clears data while preserving schema.
    Matches ClickHouse pattern - simple execution without transaction handling.
    """
    from django.db import connection

    # Truncate all sqlx-managed tables (CASCADE handles foreign keys)
    with connection.cursor() as cursor:
        cursor.execute("""
            TRUNCATE TABLE posthog_cohortpeople CASCADE;
            TRUNCATE TABLE posthog_person_new CASCADE;
            TRUNCATE TABLE posthog_person CASCADE;
            TRUNCATE TABLE posthog_persondistinctid CASCADE;
            TRUNCATE TABLE posthog_personlessdistinctid CASCADE;
            TRUNCATE TABLE posthog_personoverridemapping CASCADE;
            TRUNCATE TABLE posthog_personoverride CASCADE;
            TRUNCATE TABLE posthog_pendingpersonoverride CASCADE;
            TRUNCATE TABLE posthog_flatpersonoverride CASCADE;
            TRUNCATE TABLE posthog_featureflaghashkeyoverride CASCADE;
            TRUNCATE TABLE posthog_group CASCADE;
            TRUNCATE TABLE posthog_grouptypemapping CASCADE;
        """)


def run_persons_sqlx_migrations():
    """Run sqlx migrations for persons tables in test database.

    This creates posthog_person_new and related tables needed for dual-table
    person model migration. Mirrors production migrations in rust/persons_migrations/.
    """
    # Build database URL from Django test database settings
    # pytest-django mutates settings.DATABASES["default"]["NAME"] to add "test_" prefix
    # before this runs, so we correctly get "test_posthog" not "posthog"
    db_config = settings.DATABASES["default"]
    db_name = db_config["NAME"]
    db_user = db_config["USER"]
    db_password = db_config["PASSWORD"]
    db_host = db_config["HOST"]
    db_port = db_config["PORT"]

    # URL encode password to handle special characters
    password_part = f":{quote_plus(db_password)}" if db_password else ""
    database_url = f"postgres://{db_user}{password_part}@{db_host}:{db_port}/{db_name}"

    # Get path to migrations (relative to this file)
    # conftest.py is at posthog/conftest.py, go up one level to repo root
    migrations_path = os.path.join(os.path.dirname(__file__), "..", "rust", "persons_migrations")
    migrations_path = os.path.abspath(migrations_path)

    env = {**os.environ, "DATABASE_URL": database_url}

    # Create database if it doesn't exist (idempotent)
    try:
        subprocess.run(
            ["sqlx", "database", "create"],
            env=env,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to create test database with sqlx. "
            f"Ensure sqlx-cli is installed. Error: {e.stderr.decode() if e.stderr else str(e)}"
        ) from e

    # Run migrations
    try:
        subprocess.run(
            ["sqlx", "migrate", "run", "--source", migrations_path],
            env=env,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stdout = e.stdout.decode() if e.stdout else ""
        stderr = e.stderr.decode() if e.stderr else ""
        raise RuntimeError(
            f"Failed to run sqlx migrations from {migrations_path}.\n" f"stdout: {stdout}\nstderr: {stderr}"
        ) from e


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_keepdb, django_db_blocker):
    # Django migrations have run (via django_db_setup parameter)

    # ClickHouse setup
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
    create_clickhouse_tables()

    # Persons tables setup (parallel to ClickHouse)
    with django_db_blocker.unblock():
        create_persons_tables()

    yield

    if django_db_keepdb:
        # Reset ClickHouse data, unless we're running AI evals, where we want to keep the DB between runs
        if not settings.IN_EVAL_TESTING:
            reset_clickhouse_tables()
            with django_db_blocker.unblock():
                reset_persons_tables()
    else:
        database.drop_database()


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


@pytest.fixture(autouse=True)
def mock_two_factor_sso_enforcement_check(request, mocker):
    """
    Mock the two_factor_session.is_domain_sso_enforced check to return False for all tests.
    Can be disabled by using @pytest.mark.no_mock_two_factor_sso_enforcement_check decorator.
    """
    if "no_mock_two_factor_sso_enforcement_check" in request.keywords:
        return

    mocker.patch("posthog.helpers.two_factor_session.is_domain_sso_enforced", return_value=False)
    mocker.patch("posthog.helpers.two_factor_session.is_sso_authentication_backend", return_value=False)


@pytest.fixture(autouse=True)
def mock_email_mfa_verifier(request, mocker):
    """
    Mock the EmailMFAVerifier.should_send_email_mfa_verification method to return False for all tests.
    Can be disabled by using @pytest.mark.disable_mock_email_mfa_verifier decorator.
    """
    if "disable_mock_email_mfa_verifier" in request.keywords:
        return

    mocker.patch(
        "posthog.helpers.two_factor_session.EmailMFAVerifier.should_send_email_mfa_verification", return_value=False
    )


@pytest.fixture(autouse=True)
def reset_group_tables_between_tests(request, django_db_blocker):
    """Truncate Group/GroupTypeMapping tables between tests when using --reuse-db.

    These tables are marked managed=False so Django's flush command skips them.
    With --reuse-db (default in pytest.ini), data persists between tests causing
    unique constraint violations on group_type_index.

    Only truncates these two tables (not all sqlx-managed tables) since other
    sqlx tables don't have similar constraint issues.
    """
    yield  # Let test run

    # Cleanup after test (only with --reuse-db)
    if request.config.getoption("--reuse-db"):
        from django.db import connection

        with django_db_blocker.unblock():
            with connection.cursor() as cursor:
                cursor.execute("""
                    TRUNCATE TABLE posthog_group CASCADE;
                    TRUNCATE TABLE posthog_grouptypemapping CASCADE;
                """)


def pytest_sessionstart():
    """
    A bit of a hack to get django/py-test to do table truncation between test runs for the Persons tables that are
    no longer managed by django

    EXCEPT: Don't manage tables that sqlx manages - these are handled in django_db_setup fixture
    """
    from django.apps import apps

    # Tables that sqlx manages - keep these unmanaged
    SQLX_MANAGED_MODELS = {
        "person",
        "persondistinctid",
        "personlessdistinctid",
        "personoverridemapping",
        "personoverride",
        "pendingpersonoverride",
        "flatpersonoverride",
        "featureflaghashkeyoverride",
        "cohortpeople",
        "group",
        "grouptypemapping",
    }

    unmanaged_models = [m for m in apps.get_models() if not m._meta.managed]
    for m in unmanaged_models:
        # Keep sqlx-managed models unmanaged
        if m._meta.model_name.lower() not in SQLX_MANAGED_MODELS:
            m._meta.managed = True
