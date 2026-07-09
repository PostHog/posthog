import os
import time
import subprocess
from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import quote_plus

import pytest
from posthog.test.base import PostHogTestCase, run_clickhouse_statement_in_parallel

try:
    from hogli_commands.quarantine.pytest_support import apply_quarantine_markers
except ImportError:  # fail-open: runs without tools/hogli-commands on pythonpath (e.g. ee/pytest.ini)
    apply_quarantine_markers = None

from django.conf import settings
from django.core.management.commands.flush import Command as FlushCommand

from infi.clickhouse_orm import Database

from posthog.clickhouse.client import sync_execute
from posthog.test import flush_lock_guard


def create_clickhouse_tables():
    # Create clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from posthog.clickhouse.schema import (
        CREATE_DICTIONARY_QUERIES,
        CREATE_DISTRIBUTED_TABLE_QUERIES,
        CREATE_KAFKA_TABLE_QUERIES,
        CREATE_MERGETREE_TABLE_QUERIES,
        CREATE_MV_TABLE_QUERIES,
        CREATE_VIEW_QUERIES,
        SEED_DATA_TABLES,
        build_query,
        get_table_name,
    )

    existing_tables = {
        row[0]
        for row in sync_execute(
            "SELECT name FROM system.tables WHERE database = %(database)s",
            {"database": settings.CLICKHOUSE_DATABASE},
        )
    }

    def missing(queries):
        return [q for q in queries if get_table_name(q) not in existing_tables]

    mergetree_queries = list(map(build_query, missing(CREATE_MERGETREE_TABLE_QUERIES)))
    if mergetree_queries:
        run_clickhouse_statement_in_parallel(mergetree_queries)

    distributed_queries = list(map(build_query, missing(CREATE_DISTRIBUTED_TABLE_QUERIES)))
    if distributed_queries:
        run_clickhouse_statement_in_parallel(distributed_queries)

    if settings.IN_EVAL_TESTING:
        kafka_table_queries = list(map(build_query, missing(CREATE_KAFKA_TABLE_QUERIES)))
        if kafka_table_queries:
            run_clickhouse_statement_in_parallel(kafka_table_queries)

    mv_queries = list(map(build_query, missing(CREATE_MV_TABLE_QUERIES)))
    if mv_queries:
        run_clickhouse_statement_in_parallel(mv_queries)

    view_queries = list(map(build_query, missing(CREATE_VIEW_QUERIES)))
    if view_queries:
        run_clickhouse_statement_in_parallel(view_queries)

    dictionary_queries = list(map(build_query, missing(CREATE_DICTIONARY_QUERIES)))
    if dictionary_queries:
        run_clickhouse_statement_in_parallel(dictionary_queries)

    # Building the exchange-rate INSERT parses a 9 MB CSV and renders a ~100k-row VALUES
    # string on every pytest invocation. With a reused database the seed data is already
    # there, so skip the reload per-table (mirroring the `missing()` check above for tables).
    # Derived from SEED_DATA_TABLES in schema.py, which also drives CREATE_DATA_QUERIES,
    # so a new seed table added there is automatically picked up here.
    # TRUNCATE-based resets go through reset_clickhouse_tables, which reloads unconditionally.
    for table_name, query_fn in SEED_DATA_TABLES:
        count = sync_execute(f"SELECT count() FROM {table_name}")[0][0]
        if not count:
            run_clickhouse_statement_in_parallel([build_query(query_fn)])


def reset_clickhouse_tables():
    # Truncate clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly
    from posthog.clickhouse.dead_letter_queue import TRUNCATE_DEAD_LETTER_QUEUE_TABLE_SQL
    from posthog.clickhouse.plugin_log_entries import TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL
    from posthog.heatmaps.sql import TRUNCATE_HEATMAPS_TABLE_SQL
    from posthog.models.ai.pg_embeddings import TRUNCATE_PG_EMBEDDINGS_TABLE_SQL
    from posthog.models.ai_events.sql import TRUNCATE_AI_EVENTS_TABLE_SQL
    from posthog.models.app_metrics.sql import TRUNCATE_APP_METRICS_TABLE_SQL
    from posthog.models.channel_type.sql import TRUNCATE_CHANNEL_DEFINITION_TABLE_SQL
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

    from products.cohorts.backend.models.sql import TRUNCATE_COHORTPEOPLE_TABLE_SQL
    from products.error_tracking.backend.embedding import TRUNCATE_DOCUMENT_EMBEDDINGS_TABLE_SQL
    from products.error_tracking.backend.sql import (
        TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
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
        TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL(),
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
        TRUNCATE_AI_EVENTS_TABLE_SQL(),
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

    run_clickhouse_statement_in_parallel(list(CREATE_DATA_QUERIES()))


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

    # Point the off-ORM persons_db util (posthog/persons_db.py) at the test persons DB. It reads
    # only PERSONS_DB_{WRITER,READER}_URL from the environment, never Django settings. Derive the
    # URL from the DEFAULT connection's config (the persons DB lives on the same server, just a
    # different database) so this no longer depends on the persons_db Django alias.
    _default_db = connection.settings_dict
    _persons_user = quote_plus(_default_db.get("USER") or "")
    _persons_password = f":{quote_plus(_default_db['PASSWORD'])}" if _default_db.get("PASSWORD") else ""
    # HOST/PORT can be empty strings in Django's config (empty HOST means Unix socket);
    # fall back to localhost:5432 so the URL is always well-formed for psycopg.
    _persons_host = _default_db.get("HOST") or "localhost"
    _persons_port = _default_db.get("PORT") or "5432"
    _persons_db_url = (
        f"postgres://{_persons_user}{_persons_password}@{_persons_host}:{_persons_port}/{test_persons_db_name}"
    )
    os.environ["PERSONS_DB_WRITER_URL"] = _persons_db_url
    os.environ["PERSONS_DB_READER_URL"] = _persons_db_url

    # Update product database NAMEs to use test-prefixed names
    from posthog.product_db_config import load_product_db_routes

    for route in load_product_db_routes(settings.BASE_DIR):
        test_product_db_name = test_db_name + f"_{route.database}"
        for suffix in ("_db_writer", "_db_reader", "_db_direct"):
            alias = f"{route.database}{suffix}"
            if alias in settings.DATABASES:
                settings.DATABASES[alias]["NAME"] = test_product_db_name

    # Drop Person-related tables from default database and all FK constraints.
    # These tables exist only in the persons database, provisioned by sqlx migrations and
    # reached via off-Django psycopg — never the ORM.
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

            # Drop all persons-related tables from default database. They exist only in the
            # persons database (provisioned by sqlx migrations).
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
        # don't use the egress proxy, clickhouse is internal
        trust_env=False,
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
        # Also allow skipping reset via environment variable for faster development iteration
        skip_ch_reset = os.environ.get("SKIP_CLICKHOUSE_RESET", "0").lower() in {"1", "true", "yes"}
        if not settings.IN_EVAL_TESTING and not skip_ch_reset:
            reset_clickhouse_tables()
    else:
        database.drop_database()


@pytest.fixture(scope="package")
def django_db_setup(django_db_setup, django_db_keepdb, django_db_blocker):
    yield from _django_db_setup(django_db_keepdb, django_db_blocker)


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: Any) -> None:
    # Drain rather than iterate: products/conftest.py star-imports this hook, so it can
    # be invoked once per registering conftest.
    while flush_lock_guard.reports:
        terminalreporter.write_line(f"[flush-lock-guard] {flush_lock_guard.reports.pop(0)}", yellow=True)


def _patched_flush_handle(self, **options: Any) -> None:
    """
    Patched Django flush command for three reasons:

    1. Persons database doesn't have Django's built-in tables (contenttypes,
       permissions), so we skip post_migrate signals by truncating manually.

    2. The schema cache can be newer than the branch code, introducing tables
       Django doesn't know about. CASCADE lets TRUNCATE succeed even when
       unknown FK constraints reference a table being flushed.

    3. TRUNCATE waits on an ACCESS EXCLUSIVE lock, so one leaked idle-in-transaction
       session (e.g. from a background worker thread) hangs teardown until the CI job
       timeout. flush_lock_guard turns that silent hang into a loud, self-healing
       terminate-and-retry.

    Applied at module level (not via monkeypatch) so it stays active during
    pytest-django's _post_teardown, which runs flush AFTER function-scoped
    fixture teardown.
    """
    database = options["database"]

    options["allow_cascade"] = True
    flush: Callable[[], None] = partial(_original_flush_handle, self, **options)

    flush_lock_guard.flush_with_lock_guard(database, flush)


_original_flush_handle = FlushCommand.handle
FlushCommand.handle = _patched_flush_handle  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]


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
def mock_code_based_verifier(request, mocker):
    """
    Mock the CodeBasedVerifier.should_send_code_based_verification method to return False for all tests.
    Can be disabled by using @pytest.mark.disable_mock_code_based_verifier decorator.
    """
    from posthog.helpers.two_factor_session import CodeBasedVerificationCheckResult

    if "disable_mock_code_based_verifier" in request.keywords:
        return

    mocker.patch(
        "posthog.helpers.two_factor_session.CodeBasedVerifier.should_send_code_based_verification",
        return_value=CodeBasedVerificationCheckResult(should_send=False),
    )


class _JUnitTimingsPlugin:
    """Capture wall-clock offsets and surface them as JUnit `<testsuite>` properties.

    Pytest's junit XML emits one `time` per `<testcase>` but no per-test start. The
    CI trace exporter (`.github/scripts/report_test_timings.py`) reconstructs windows
    by stacking durations from `<testsuite timestamp>`, so the shared pre-first-test
    overhead (interpreter import, plugin init, collection, session/package fixture
    setup) gets visually attributed to the first test span. We record the offset
    explicitly so the exporter can split it into its own span.

    Important: this measures up to the first test's *call* phase, not its setup
    phase. The backend CI uses `-o junit_duration_report=call`, so session and
    module-scoped fixture setup time is excluded from `<testcase time>` and
    instead lives in this pre-first-call gap.

    Also records pytest-rerunfailures retries as a `<testcase>` property: pytest's
    junitxml appends children only for passed/failed/skipped reports, so a rerun
    report leaves no trace and a flaky fail-then-pass serializes as a clean
    `<testcase/>` — invisible to flaky-test telemetry.
    """

    _PROPERTY_SETUP = "posthog.setup_seconds"
    _PROPERTY_COLLECTION = "posthog.collection_seconds"
    _PROPERTY_RERUNS = "posthog.reruns"

    def __init__(self) -> None:
        self._session_start: float | None = None
        self._collection_finish: float | None = None
        self._first_test_call_start: float | None = None

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self._session_start = time.monotonic()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if self._collection_finish is None:
            self._collection_finish = time.monotonic()

    # `tryfirst` so our timestamp lands just before pytest's default call impl
    # actually runs the test body — capturing the moment the first call begins,
    # after session/module fixture setup has completed.
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self, item: pytest.Item) -> None:
        if self._first_test_call_start is None:
            self._first_test_call_start = time.monotonic()

    # `tryfirst` so the property is on the report before junitxml's own
    # logreport consumes `user_properties` into the `<testcase>` element.
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        reruns = getattr(report, "rerun", 0) or 0  # attempt index, set by pytest-rerunfailures
        # str() widens TestReport.outcome's Literal: "rerun" is assigned by pytest-rerunfailures.
        if not reruns or report.when != "teardown" or str(report.outcome) == "rerun":
            return
        # Appended exactly once: intermediate attempts never log a non-rerun teardown,
        # and each report owns its own copy of `user_properties`.
        report.user_properties.append((self._PROPERTY_RERUNS, str(reruns)))

    @staticmethod
    def _find_junit_xml_plugin(config: pytest.Config) -> Any:
        # pytest's junit XML plugin (`_pytest.junitxml.LogXML`) registers itself
        # without a stable name — `get_plugin("junitxml")` returns the module, not
        # the instance — so we identify it by its `add_global_property` interface.
        for _, plugin in config.pluginmanager.list_name_plugin():
            if hasattr(plugin, "add_global_property"):
                return plugin
        return None

    # Must run before pytest_junitxml's own sessionfinish, which serializes the XML
    # and stops consuming new `add_global_property` calls after that point.
    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self._session_start is None:
            return
        xml = self._find_junit_xml_plugin(session.config)
        if xml is None:
            return
        if self._first_test_call_start is not None:
            xml.add_global_property(self._PROPERTY_SETUP, f"{self._first_test_call_start - self._session_start:.6f}")
        if self._collection_finish is not None:
            xml.add_global_property(self._PROPERTY_COLLECTION, f"{self._collection_finish - self._session_start:.6f}")


def pytest_configure(config):
    """
    Configure pytest-django to allow access to persons databases by default.
    This is needed for tests that don't inherit from PostHogTestCase.
    Most tests inherit from PostHogTestCase which already sets databases correctly,
    but this ensures any remaining TestCase/TransactionTestCase also have access.
    """
    from django.test import TestCase, TransactionTestCase

    # Set default databases for Django test classes
    TestCase.databases = {"default"}
    TransactionTestCase.databases = {"default"}

    if not config.pluginmanager.hasplugin("posthog-junit-timings"):
        config.pluginmanager.register(_JUnitTimingsPlugin(), "posthog-junit-timings")


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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if apply_quarantine_markers is not None:
        apply_quarantine_markers(items)
