import os
import subprocess
from urllib.parse import quote_plus

import pytest
from posthog.test.base import PostHogTestCase, run_clickhouse_statement_in_parallel

from django.conf import settings
from django.core.management.commands.flush import Command as FlushCommand
from django.db import connections

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


def run_persons_sqlx_migrations(keepdb: bool = False):
    """Run sqlx migrations for persons tables in separate test_posthog_persons database.

    This creates posthog_person_new and related tables needed for dual-table
    person model migration. Mirrors production migrations in rust/persons_migrations/.
    Uses a separate database to mirror production setup where persons live in their own DB.

    Args:
        keepdb: If True, reuse existing database (only create if missing). If False, drop and recreate.
    """
    # Build database URL for test_posthog_persons (separate from main test_posthog)
    db_config = settings.DATABASES["default"]
    # Use separate persons database name to mirror production
    persons_db_name = db_config["NAME"] + "_persons"
    db_user = db_config["USER"]
    db_password = db_config["PASSWORD"]
    db_host = db_config["HOST"]
    db_port = db_config["PORT"]

    # URL encode password to handle special characters
    password_part = f":{quote_plus(db_password)}" if db_password else ""
    database_url = f"postgres://{db_user}{password_part}@{db_host}:{db_port}/{persons_db_name}"

    # Get path to migrations (relative to this file)
    # conftest.py is at posthog/conftest.py, go up one level to repo root
    migrations_path = os.path.join(os.path.dirname(__file__), "..", "rust", "persons_migrations")
    migrations_path = os.path.abspath(migrations_path)

    env = {**os.environ, "DATABASE_URL": database_url}

    if not keepdb:
        # Drop and recreate database to ensure clean state
        try:
            subprocess.run(
                ["sqlx", "database", "drop", "-y"],
                env=env,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Database might not exist, which is fine
            pass

    # Create database (idempotent - will succeed if already exists)
    try:
        subprocess.run(
            ["sqlx", "database", "create"],
            env=env,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        # If keepdb=True and database exists, this is expected to fail - that's fine
        if not keepdb:
            raise RuntimeError(
                f"Failed to create test database with sqlx. "
                f"Ensure sqlx-cli is installed. Error: {e.stderr.decode() if e.stderr else str(e)}"
            ) from e

    # Run migrations (idempotent - sqlx tracks which migrations have run)
    try:
        subprocess.run(
            ["sqlx", "migrate", "run", "--source", migrations_path],
            env=env,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to run sqlx migrations from {migrations_path}. Error: {e.stderr.decode() if e.stderr else str(e)}"
        ) from e


def _django_db_setup(django_db_keepdb, django_db_blocker):
    # Django migrations have run (via django_db_setup parameter)
    # Configure persons database now that we know the actual test database name
    from django.db import connection

    # Get the actual test database name (with test_ prefix added by pytest-django)
    test_db_name = connection.settings_dict["NAME"]
    test_persons_db_name = test_db_name + "_persons"

    # Update the persons database NAME to use the correct test database name
    # The database configuration already exists from settings, we just need to update the NAME
    settings.DATABASES["persons_db_writer"]["NAME"] = test_persons_db_name
    settings.DATABASES["persons_db_reader"]["NAME"] = test_persons_db_name

    # Drop Person-related tables from default database and all FK constraints
    # These tables will exist in the persons_db_writer database via sqlx migrations
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            # Drop all FK constraints pointing to posthog_person, regardless of naming convention
            # This is needed because:
            # 1. Django creates FKs with hash suffix: posthog_persondistin_person_id_5d655bba_fk_posthog_p
            # 2. sqlx migration tries to drop: posthog_persondistinctid_person_id_fkey
            # 3. Mismatch means FK remains and blocks dual-table writes
            cursor.execute("""
                DO $$
                DECLARE r RECORD;
                BEGIN
                    -- Only drop if posthog_person table exists
                    IF EXISTS (SELECT FROM pg_tables WHERE tablename = 'posthog_person') THEN
                        FOR r IN
                            SELECT conname, conrelid::regclass AS table_name
                            FROM pg_constraint
                            WHERE contype = 'f'
                            AND confrelid = 'posthog_person'::regclass
                        LOOP
                            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.table_name, r.conname);
                        END LOOP;
                    END IF;
                END $$;
            """)

            # Drop all persons-related tables from default database
            # These will exist in the persons_db_writer database via sqlx migrations
            # Drop in correct order: dependent tables first, then referenced tables
            cursor.execute("""
                DROP TABLE IF EXISTS posthog_cohortpeople CASCADE;
                DROP TABLE IF EXISTS posthog_featureflaghashkeyoverride CASCADE;
                DROP TABLE IF EXISTS posthog_group CASCADE;
                DROP TABLE IF EXISTS posthog_grouptypemapping CASCADE;
                DROP TABLE IF EXISTS posthog_persondistinctid CASCADE;
                DROP TABLE IF EXISTS posthog_personlessdistinctid CASCADE;
                DROP TABLE IF EXISTS posthog_personoverride CASCADE;
                DROP TABLE IF EXISTS posthog_pendingpersonoverride CASCADE;
                DROP TABLE IF EXISTS posthog_flatpersonoverride CASCADE;
                DROP TABLE IF EXISTS posthog_personoverridemapping CASCADE;
                DROP TABLE IF EXISTS posthog_person CASCADE;
            """)

    # Run sqlx migrations to create posthog_person_new and related tables
    run_persons_sqlx_migrations(keepdb=django_db_keepdb)

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

    yield

    if django_db_keepdb:
        # Reset ClickHouse data, unless we're running AI evals, where we want to keep the DB between runs
        if not settings.IN_EVAL_TESTING:
            reset_clickhouse_tables()
    else:
        database.drop_database()


@pytest.fixture(scope="package")
def django_db_setup(django_db_setup, django_db_keepdb, django_db_blocker):
    yield from _django_db_setup(django_db_keepdb, django_db_blocker)


@pytest.fixture(autouse=True)
def patch_flush_command_for_persons_db(monkeypatch):
    """
    Patch Django's flush command to handle persons database properly.

    Persons database doesn't have Django's built-in tables (contenttypes, permissions, etc.),
    so we need to skip emitting post_migrate signals that would try to create them.

    This is needed for non-Django test classes (pytest, temporal, async tests).
    Django test classes handle this in _fixture_teardown in test/base.py.
    """
    original_handle = FlushCommand.handle

    def patched_handle(self, **options):
        database = options.get("database")

        if database in ("persons_db_writer", "persons_db_reader"):
            # Manually truncate persons database tables without emitting signals
            conn = connections[database]
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename NOT LIKE 'pg_%'
                    AND tablename NOT LIKE '_sqlx_%'
                    AND tablename NOT LIKE '_persons_migrations'
                """)
                tables = [row[0] for row in cursor.fetchall()]
                if tables:
                    cursor.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
        else:
            return original_handle(self, **options)

    monkeypatch.setattr(FlushCommand, "handle", patched_handle)


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
    from posthog.helpers.two_factor_session import EmailMFACheckResult

    if "disable_mock_email_mfa_verifier" in request.keywords:
        return

    mocker.patch(
        "posthog.helpers.two_factor_session.EmailMFAVerifier.should_send_email_mfa_verification",
        return_value=EmailMFACheckResult(should_send=False),
    )


def pytest_configure(config):
    """
    Configure pytest-django to allow access to persons databases by default.
    This is needed for tests that don't inherit from PostHogTestCase.
    Most tests inherit from PostHogTestCase which already sets databases correctly,
    but this ensures any remaining TestCase/TransactionTestCase also have access.
    """
    from django.test import TestCase, TransactionTestCase

    # Set default databases for Django test classes
    TestCase.databases = {"default", "persons_db_writer", "persons_db_reader"}
    TransactionTestCase.databases = {"default", "persons_db_writer", "persons_db_reader"}


def _runs_on_internal_pr() -> bool:
    """
    Returns True when tests are running for an internal PR or on master,
    and False for fork PRs.
    Defaults to True, so local runs are unaffected.
    """
    value = os.getenv("RUNS_ON_INTERNAL_PR")
    if value is None:
        return True
    return value.lower() in {"1", "true"}


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "requires_secrets" in item.keywords and not _runs_on_internal_pr():
        pytest.skip("Skipping test that requires internal secrets on external PRs")
