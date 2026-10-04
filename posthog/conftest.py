import os
import time
import logging
import warnings
import subprocess
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote_plus

import pytest
from posthog.test.base import PostHogTestCase, _selective_flush, run_clickhouse_statement_in_parallel

from _pytest.junitxml import ET, bin_xml_escape, mangle_test_address

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter

try:
    from hogli_commands.quarantine.pytest_support import apply_quarantine_markers
except ImportError:  # fail-open: runs without tools/hogli-commands on pythonpath
    apply_quarantine_markers = None

from django.conf import settings
from django.core.management.commands.flush import Command as FlushCommand
from django.db import connections
from django.test import TransactionTestCase

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.managed_schema import ClickHouseDatabase
from posthog.cloud_utils import is_ci
from posthog.test import flush_lock_guard

logger = logging.getLogger(__name__)


@pytest.fixture(scope="package")
def clickhouse_database() -> None:
    # SQL-only tests need a database without the Postgres setup tied to django_db_setup.
    ClickHouseDatabase().create()


def create_clickhouse_tables():
    # Kafka tables are left out: nothing consumes in tests, and some tests do not expect them.
    database = ClickHouseDatabase()
    database.create_test_tables(kafka=settings.IN_EVAL_TESTING)


def reset_clickhouse_tables():
    # Truncate clickhouse tables to default before running test
    # Mostly so that test runs locally work correctly

    # Drop created Kafka tables because some tests don't expect it.
    # Using `ON CLUSTER` takes x20 more time to drop the tables: https://github.com/ClickHouse/ClickHouse/issues/15473.
    statements = [
        f"DROP TABLE `{name}`" if engine == "Kafka" else f"TRUNCATE TABLE `{name}`"
        for name, engine in sync_execute(
            # Skip tables ClickHouse reports as empty: each truncate costs a keeper round-trip on
            # replicated engines, and pure-Postgres sessions never write to these tables at all.
            """
            SELECT name, engine
            FROM system.tables
            WHERE database = %(database)s
              AND ((engine LIKE '%%MergeTree' AND total_rows > 0) OR (engine = 'Kafka' AND %(drop_kafka)s))
            """,
            {"database": settings.CLICKHOUSE_DATABASE, "drop_kafka": settings.IN_EVAL_TESTING},
        )
    ]
    run_clickhouse_statement_in_parallel(statements)

    ClickHouseDatabase().seed()


def _sqlx_error_output(error: subprocess.CalledProcessError) -> str:
    output = "\n".join(
        stream.decode(errors="replace") if isinstance(stream, bytes) else stream
        for stream in (error.stdout, error.stderr)
        if stream
    )
    return output or str(error)


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
    if not persons_db_name.startswith("test_"):
        raise RuntimeError(
            f"Refusing to run persons migrations against '{persons_db_name}', which is not a test database. "
            "Add a pytest.mark.django_db marker to the test module."
        )
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
                f"Ensure sqlx-cli is installed. Error: {_sqlx_error_output(e)}"
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
            f"Failed to run sqlx migrations from {migrations_path}. Error: {_sqlx_error_output(e)}"
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

    database = ClickHouseDatabase()

    if not django_db_keepdb:
        database.drop()

    database.create()  # Create database if it doesn't exist

    create_clickhouse_tables()

    # Seed default data that historically lived in RunPython migrations. Squashed
    # migrations drop those ops, so without this tests relying on the defaults
    # (Billing Team auth group, Default DataColorTheme, starter DashboardTemplates)
    # would fail on a fresh test DB. Tolerated: in some shards (e.g. temporal
    # async tests that only need the persons DB) the default DB schema isn't
    # fully migrated yet — skip seeding rather than break setup.
    with django_db_blocker.unblock():
        from django.core.management import call_command

        try:
            call_command("ensure_migration_defaults", verbosity=0)
        except Exception as exc:
            warnings.warn(
                f"ensure_migration_defaults skipped during test DB setup: {exc}",
                stacklevel=2,
            )

    yield

    if django_db_keepdb:
        # Reset ClickHouse data, unless we're running AI evals, where we want to keep the DB between runs
        # Also allow skipping reset via environment variable for faster development iteration
        skip_ch_reset = os.environ.get("SKIP_CLICKHOUSE_RESET", "0").lower() in {"1", "true", "yes"}
        if not settings.IN_EVAL_TESTING and not skip_ch_reset:
            reset_clickhouse_tables()
    else:
        database.drop()


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
FlushCommand.handle = _patched_flush_handle  # type: ignore[method-assign]


def _another_session_is_busy(db_name: str) -> bool:
    with connections[db_name].cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT FROM pg_stat_activity WHERE datname = current_database()"
            " AND pid <> pg_backend_pid() AND backend_type = 'client backend' AND state <> 'idle')"
        )
        return cursor.fetchone() == (True,)


def _patched_fixture_teardown(self: TransactionTestCase) -> None:
    """
    Use the selective flush of NonAtomicBaseTest instead of the stock flush, which truncates every
    table and re-seeds content types and permissions after each ``django_db(transaction=True)`` test.

    Keep the stock flush while another session is busy, such as a Temporal worker thread: TRUNCATE
    waits for that session's transaction, but the selective probe and DELETE do not, so rows it
    commits later would leak into the next test.
    """
    db_names = cast(Any, self)._databases_names(include_mirrors=False)
    if self.available_apps is not None or self.serialized_rollback or any(map(_another_session_is_busy, db_names)):
        _original_fixture_teardown(self)
        return
    try:
        for db_name in db_names:
            _selective_flush(db_name, reset_sequences=False)
    except Exception:
        logger.exception("Selective flush failed; falling back to the stock teardown")
        _original_fixture_teardown(self)


_original_fixture_teardown = TransactionTestCase._fixture_teardown  # type: ignore[attr-defined]
TransactionTestCase._fixture_teardown = _patched_fixture_teardown  # type: ignore[attr-defined]


@pytest.fixture
def base_test_mixin_fixture():
    # setUpTestData is a classmethod. On PostHogTestCase itself it would write the rows onto the
    # shared base class, where a later test class that has not set up its own data yet reads a
    # team this test already rolled back.
    kls = type("BaseTestMixinFixture", (PostHogTestCase,), {})()
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

    Also records pytest-rerunfailures retries as a `<testcase>` property.
    Pytest's JUnit output omits intermediate rerun reports, so a separate
    JUnit file preserves their failures for Trunk.
    """

    _PROPERTY_SETUP = "posthog.setup_seconds"
    _PROPERTY_COLLECTION = "posthog.collection_seconds"
    _PROPERTY_RERUNS = "posthog.reruns"

    def __init__(self) -> None:
        self._session_start: float | None = None
        self._collection_finish: float | None = None
        self._first_test_call_start: float | None = None
        self._retry_reports: list[pytest.TestReport] = []

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
        if str(report.outcome) == "rerun":
            self._retry_reports.append(report)
        # str() widens TestReport.outcome's Literal: "rerun" is assigned by pytest-rerunfailures.
        if not reruns or report.when != "teardown" or str(report.outcome) == "rerun":
            return
        # Appended exactly once: intermediate attempts never log a non-rerun teardown,
        # and each report owns its own copy of `user_properties`.
        report.user_properties.append((self._PROPERTY_RERUNS, str(reruns)))
        if runner_name := os.environ.get("RUNNER_NAME"):
            report.user_properties.append(("posthog.runner_name", runner_name))

    def pytest_terminal_summary(self, terminalreporter: "TerminalReporter") -> None:
        if not terminalreporter.hasopt("R"):
            return
        # pytest-rerunfailures 16.1's summary lists nodeids but omits the failed attempt's traceback.
        for report in terminalreporter.stats.get("rerun", []):
            terminalreporter.write_sep("_", f"RERUN {report.nodeid} ({report.when})")
            report.toterminal(terminalreporter._tw)
            # Anchor the final exception within the log-thinning context window.
            terminalreporter.write_sep("_", f"RERUN END {report.nodeid} ({report.when})")

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
        self._write_retry_junit(xml)

    def _write_retry_junit(self, xml: Any) -> None:
        source_path = Path(xml.logfile)
        retry_path = source_path.with_name(f"{source_path.stem}-retry-failures.xml")
        if not self._retry_reports:
            retry_path.unlink(missing_ok=True)
            return

        failures = sum(report.when == "call" for report in self._retry_reports)
        suite = ET.Element(
            "testsuite",
            name=xml.suite_name,
            tests=str(len(self._retry_reports)),
            failures=str(failures),
            errors=str(len(self._retry_reports) - failures),
            skipped="0",
            time=f"{sum(report.duration for report in self._retry_reports):.3f}",
            timestamp=xml.suite_start.as_utc().astimezone().isoformat(),
        )
        for report in self._retry_reports:
            names = mangle_test_address(report.nodeid)
            classnames = names[:-1]
            if xml.prefix:
                classnames.insert(0, xml.prefix)
            attrs = {
                "classname": ".".join(classnames),
                "name": bin_xml_escape(names[-1]),
                "file": report.location[0],
                "time": f"{report.duration:.3f}",
                "attempt_number": str(getattr(report, "rerun", 0) + 1),
            }
            if report.location[1] is not None:
                attrs["line"] = str(report.location[1])
            testcase = ET.SubElement(suite, "testcase", attrs)
            reprcrash = getattr(report.longrepr, "reprcrash", None)
            message = getattr(reprcrash, "message", None) or report.longreprtext or "pytest retry failed"
            tag = "failure" if report.when == "call" else "error"
            ET.SubElement(testcase, tag, message=bin_xml_escape(message)).text = bin_xml_escape(report.longreprtext)

        root = ET.Element("testsuites")
        root.append(suite)
        retry_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(retry_path, encoding="utf-8", xml_declaration=True)


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


def _vendor_credentials_present(marker: pytest.Mark) -> bool:
    check: Callable[[], bool] | None = marker.kwargs.get("check")
    return all(name in os.environ for name in marker.args) and (check is None or check())


def _describe_vendor_credentials(marker: pytest.Mark) -> str:
    check: Callable[[], bool] | None = marker.kwargs.get("check")
    return ", ".join([*marker.args, *([check.__name__] if check is not None else [])])


def _gate_vendor_credential_tests(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect vendor credential tests in CI, where they can only skip and a skip with no recorded
    pass reads as a broken test. Locally they stay collected, because a developer may export the
    credentials, and skip with a reason naming what is missing.
    """
    gated = [
        (item, marker)
        for item in items
        if (marker := item.get_closest_marker("requires_vendor_credentials")) is not None
    ]
    if not gated:
        return
    if is_ci():
        deselected = {id(item) for item, _ in gated}
        config.hook.pytest_deselected(items=[item for item, _ in gated])
        items[:] = [item for item in items if id(item) not in deselected]
        return
    for item, marker in gated:
        if not _vendor_credentials_present(marker):
            item.add_marker(
                pytest.mark.skip(reason=f"vendor credentials not available: {_describe_vendor_credentials(marker)}")
            )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if apply_quarantine_markers is not None:
        apply_quarantine_markers(items)
    _gate_vendor_credential_tests(config, items)
