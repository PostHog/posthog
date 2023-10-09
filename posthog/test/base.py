import datetime as dt
import inspect
import re
import threading
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union
from unittest.mock import patch

import freezegun
import pytest
import sqlparse
from django.apps import apps
from django.core.cache import cache
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase as DRFTestCase

from posthog import rate_limit
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ch_pool
from posthog.clickhouse.plugin_log_entries import TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL
from posthog.cloud_utils import TEST_clear_cloud_cache, TEST_clear_instance_license_cache, is_cloud
from posthog.models import Dashboard, DashboardTile, Insight, Organization, Team, User
from posthog.models.cohort.sql import TRUNCATE_COHORTPEOPLE_TABLE_SQL
from posthog.models.event.sql import DISTRIBUTED_EVENTS_TABLE_SQL, DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
from posthog.models.event.util import bulk_create_events
from posthog.models.group.sql import TRUNCATE_GROUPS_TABLE_SQL
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import OrganizationMembership
from posthog.models.person import Person
from posthog.models.person.sql import (
    DROP_PERSON_TABLE_SQL,
    PERSONS_TABLE_SQL,
    TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
    TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
    TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
)
from posthog.models.person.util import bulk_create_persons, create_person
from posthog.session_recordings.sql.session_recording_event_sql import (
    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.settings.utils import get_from_env, str_to_bool
from posthog.test.assert_faster_than import assert_faster_than

# Make sure freezegun ignores our utils class that times functions
freezegun.configure(extend_ignore_list=["posthog.test.assert_faster_than"])  # type: ignore


persons_cache_tests: List[Dict[str, Any]] = []
events_cache_tests: List[Dict[str, Any]] = []
persons_ordering_int: int = 1


def _setup_test_data(klass):
    klass.organization = Organization.objects.create(name=klass.CONFIG_ORGANIZATION_NAME)
    klass.team = Team.objects.create(
        organization=klass.organization,
        api_token=klass.CONFIG_API_TOKEN,
        test_account_filters=[{"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}],
        has_completed_onboarding_for={"product_analytics": True},
    )
    if klass.CONFIG_EMAIL:
        klass.user = User.objects.create_and_join(klass.organization, klass.CONFIG_EMAIL, klass.CONFIG_PASSWORD)
        klass.organization_membership = klass.user.organization_memberships.get()


class FuzzyInt(int):
    """
    Some query count assertions vary depending on the order of tests in the run because values are cached and so their related query doesn't always run.

    For the purposes of testing query counts we don't care about that variation
    """

    lowest: int
    highest: int

    def __new__(cls, lowest, highest):
        obj = super(FuzzyInt, cls).__new__(cls, highest)
        obj.lowest = lowest
        obj.highest = highest
        return obj

    def __eq__(self, other):
        return self.lowest <= other <= self.highest

    def __repr__(self):
        return "[%d..%d]" % (self.lowest, self.highest)


class ErrorResponsesMixin:
    ERROR_INVALID_CREDENTIALS = {
        "type": "validation_error",
        "code": "invalid_credentials",
        "detail": "Invalid email or password.",
        "attr": None,
    }

    def not_found_response(self, message: str = "Not found.") -> Dict[str, Optional[str]]:
        return {"type": "invalid_request", "code": "not_found", "detail": message, "attr": None}

    def permission_denied_response(
        self, message: str = "You do not have permission to perform this action."
    ) -> Dict[str, Optional[str]]:
        return {"type": "authentication_error", "code": "permission_denied", "detail": message, "attr": None}

    def method_not_allowed_response(self, method: str) -> Dict[str, Optional[str]]:
        return {
            "type": "invalid_request",
            "code": "method_not_allowed",
            "detail": f'Method "{method}" not allowed.',
            "attr": None,
        }

    def unauthenticated_response(
        self, message: str = "Authentication credentials were not provided.", code: str = "not_authenticated"
    ) -> Dict[str, Optional[str]]:
        return {"type": "authentication_error", "code": code, "detail": message, "attr": None}

    def validation_error_response(
        self, message: str = "Malformed request", code: str = "invalid_input", attr: Optional[str] = None
    ) -> Dict[str, Optional[str]]:
        return {"type": "validation_error", "code": code, "detail": message, "attr": attr}


class TestMixin:
    CONFIG_ORGANIZATION_NAME: str = "Test"
    CONFIG_EMAIL: Optional[str] = "user1@posthog.com"
    CONFIG_PASSWORD: Optional[str] = "testpassword12345"
    CONFIG_API_TOKEN: str = "token123"
    CONFIG_AUTO_LOGIN: bool = True
    # Most test cases can run with class data level setup. This means that test data gets set up once per class,
    # which can greatly speed up tests. Some tests will require test data to be set up on every test case, setting this
    # to `False` will set up test data on every test case instead.
    CLASS_DATA_LEVEL_SETUP = True

    # Test data definition stubs
    organization: Organization = None  # type: ignore
    team: Team = None  # type: ignore
    user: User = None  # type: ignore
    organization_membership: OrganizationMembership = None  # type: ignore

    def _create_user(self, email: str, password: Optional[str] = None, first_name: str = "", **kwargs) -> User:
        return User.objects.create_and_join(self.organization, email, password, first_name, **kwargs)

    @classmethod
    def setUpTestData(cls):
        if cls.CLASS_DATA_LEVEL_SETUP:
            _setup_test_data(cls)

    def setUp(self):
        if get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            from posthog.models.team import util

            util.can_enable_actor_on_events = True

        if not self.CLASS_DATA_LEVEL_SETUP:
            _setup_test_data(self)

    def tearDown(self):
        if len(persons_cache_tests) > 0:
            persons_cache_tests.clear()
            raise Exception(
                "Some persons created in this test weren't flushed, which can lead to inconsistent test results. Add flush_persons_and_events() right after creating all persons."
            )

        if len(events_cache_tests) > 0:
            events_cache_tests.clear()
            raise Exception(
                "Some events created in this test weren't flushed, which can lead to inconsistent test results. Add flush_persons_and_events() right after creating all events."
            )
        global persons_ordering_int
        persons_ordering_int = 0
        super().tearDown()  # type: ignore

    def validate_basic_html(self, html_message, site_url, preheader=None):
        # absolute URLs are used
        self.assertIn(f"{site_url}/static/posthog-logo.png", html_message)  # type: ignore

        # CSS is inlined
        self.assertIn('style="display: none;', html_message)  # type: ignore

        if preheader:
            self.assertIn(preheader, html_message)  # type: ignore


class BaseTest(TestMixin, ErrorResponsesMixin, TestCase):
    """
    Base class for performing Postgres-based backend unit tests on.
    Each class and each test is wrapped inside an atomic block to rollback DB commits after each test.
    Read more: https://docs.djangoproject.com/en/3.1/topics/testing/tools/#testcase
    """

    @contextmanager
    def is_cloud(self, value: bool):
        previous_value = is_cloud()
        try:
            TEST_clear_cloud_cache(value)
            yield value
        finally:
            TEST_clear_cloud_cache(previous_value)


class NonAtomicBaseTest(TestMixin, ErrorResponsesMixin, TransactionTestCase):
    """
    Django wraps tests in TestCase inside atomic transactions to speed up the run time. TransactionTestCase is the base
    class for TestCase that doesn't implement this atomic wrapper.
    Read more: https://avilpage.com/2020/01/disable-transactions-django-tests.html
    """

    @classmethod
    def setUpClass(cls):
        cls.setUpTestData()


class APIBaseTest(TestMixin, ErrorResponsesMixin, DRFTestCase):
    """
    Functional API tests using Django REST Framework test suite.
    """

    initial_cloud_mode: Optional[bool] = False

    def setUp(self):
        super().setUp()

        cache.clear()
        TEST_clear_cloud_cache(self.initial_cloud_mode)
        TEST_clear_instance_license_cache()

        # Sets the cloud mode to stabilise things tests, especially num query counts
        # Clear the is_rate_limit lru_Caches so that they does not flap in test snapshots
        rate_limit.is_rate_limit_enabled.cache_clear()
        rate_limit.get_team_allow_list.cache_clear()

        if self.CONFIG_AUTO_LOGIN and self.user:
            self.client.force_login(self.user)

    def assertEntityResponseEqual(self, response1, response2, remove=("action", "label", "persons_urls", "filter")):
        stripped_response1 = stripResponse(response1, remove=remove)
        stripped_response2 = stripResponse(response2, remove=remove)
        self.assertDictEqual(stripped_response1[0], stripped_response2[0])

    @contextmanager
    def assertFasterThan(self, duration_ms: float):
        with assert_faster_than(duration_ms):
            yield

    @contextmanager
    def is_cloud(self, value: bool):
        # Typically the is_cloud setting is controlled by License but we need to be able to override it for tests
        previous_value = is_cloud()
        try:
            TEST_clear_cloud_cache(value)
            yield value
        finally:
            TEST_clear_cloud_cache(previous_value)


def stripResponse(response, remove=("action", "label", "persons_urls", "filter")):
    if len(response):
        for attr in remove:
            if attr in response[0]:
                response[0].pop(attr)
    return response


def default_materialised_columns():
    try:
        from ee.clickhouse.materialized_columns.analyze import get_materialized_columns
        from ee.clickhouse.materialized_columns.test.test_columns import EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS

    except:
        # EE not available? Skip
        return []

    default_columns = []
    for prop in EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS:
        column_name = get_materialized_columns("events")[(prop, "properties")]
        default_columns.append(column_name)

    return default_columns


def cleanup_materialized_columns():
    try:
        from ee.clickhouse.materialized_columns.analyze import get_materialized_columns
    except:
        # EE not available? Skip
        return

    default_columns = default_materialised_columns()
    for column_name in get_materialized_columns("events").values():
        if column_name not in default_columns:
            sync_execute(f"ALTER TABLE events DROP COLUMN {column_name}")
    for column_name in get_materialized_columns("person").values():
        sync_execute(f"ALTER TABLE person DROP COLUMN {column_name}")
    for column_name in get_materialized_columns("groups").values():
        sync_execute(f"ALTER TABLE groups DROP COLUMN {column_name}")


def also_test_with_materialized_columns(
    event_properties=[],
    person_properties=[],
    group_properties=[],
    verify_no_jsonextract=True,
    # :TODO: Remove this when groups-on-events is released
    materialize_only_with_person_on_events=False,
):
    """
    Runs the test twice on clickhouse - once verifying it works normally, once with materialized columns.

    Requires a unittest class with ClickhouseTestMixin mixed in
    """

    try:
        from ee.clickhouse.materialized_columns.analyze import materialize
    except:
        # EE not available? Just run the main test
        return lambda fn: fn

    if materialize_only_with_person_on_events and not get_from_env(
        "PERSON_ON_EVENTS_ENABLED", False, type_cast=str_to_bool
    ):
        # Don't run materialized test unless PERSON_ON_EVENTS_ENABLED
        return lambda fn: fn

    def decorator(fn):
        @pytest.mark.ee
        def fn_with_materialized(self, *args, **kwargs):
            # Don't run these tests under non-clickhouse classes even if decorated in base classes
            if not getattr(self, "RUN_MATERIALIZED_COLUMN_TESTS", False):
                return

            for prop in event_properties:
                materialize("events", prop)
            for prop in person_properties:
                materialize("person", prop)
                materialize("events", prop, table_column="person_properties")
            for group_type_index, prop in group_properties:
                materialize("events", prop, table_column=f"group{group_type_index}_properties")  # type: ignore

            try:
                with self.capture_select_queries() as sqls:
                    fn(self, *args, **kwargs)
            finally:
                cleanup_materialized_columns()

            if verify_no_jsonextract:
                for sql in sqls:
                    self.assertNotIn("JSONExtract", sql)

        # To add the test, we inspect the frame this function was called in and add the test there
        frame_locals: Any = inspect.currentframe().f_back.f_locals  # type: ignore
        frame_locals[f"{fn.__name__}_materialized"] = fn_with_materialized

        return fn

    return decorator


@pytest.mark.usefixtures("unittest_snapshot")
class QueryMatchingTest:
    snapshot: Any

    # :NOTE: Update snapshots by passing --snapshot-update to bin/tests
    def assertQueryMatchesSnapshot(self, query, params=None, replace_all_numbers=False):
        # :TRICKY: team_id changes every test, avoid it messing with snapshots.
        if replace_all_numbers:
            query = re.sub(r"(\"?) = \d+", r"\1 = 2", query)
            query = re.sub(r"(\"?) IN \(\d+(, \d+)*\)", r"\1 IN (1, 2, 3, 4, 5 /* ... */)", query)
            # feature flag conditions use primary keys as columns in queries, so replace those too
            query = re.sub(r"flag_\d+_condition", r"flag_X_condition", query)
            query = re.sub(r"flag_\d+_super_condition", r"flag_X_super_condition", query)
        else:
            query = re.sub(r"(team|cohort)_id(\"?) = \d+", r"\1_id\2 = 2", query)
            query = re.sub(r"\d+ as (team|cohort)_id(\"?)", r"2 as \1_id\2", query)

        # hog ql checks team ids differently
        query = re.sub(
            r"equals\(([^.]+\.)?team_id?, \d+\)",
            r"equals(\1team_id, 2)",
            query,
        )

        # Replace organization_id and notebook_id lookups, for postgres
        query = re.sub(
            rf"""("organization_id"|"posthog_organization"\."id"|"posthog_notebook"."id") = '[^']+'::uuid""",
            r"""\1 = '00000000-0000-0000-0000-000000000000'::uuid""",
            query,
        )
        query = re.sub(
            rf"""("organization_id"|"posthog_organization"\."id"|"posthog_notebook"."id") IN \('[^']+'::uuid\)""",
            r"""\1 IN ('00000000-0000-0000-0000-000000000000'::uuid)""",
            query,
        )

        # Replace notebook short_id lookups, for postgres
        query = re.sub(
            r"\"posthog_notebook\".\"short_id\" = '[a-zA-Z0-9]{8}'",
            '"posthog_notebook"."short_id" = \'00000000\'',
            query,
        )

        # Replace person id (when querying session recording replay events)
        query = re.sub(
            "and person_id = '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'",
            r"and person_id = '00000000-0000-0000-0000-000000000000'",
            query,
        )

        # Replace tag id lookups for postgres
        query = re.sub(
            rf"""("posthog_tag"\."id") IN \(('[^']+'::uuid)+(, ('[^']+'::uuid)+)*\)""",
            r"""\1 IN ('00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid /* ... */)""",
            query,
        )

        query = re.sub(rf"""user_id:([0-9]+) request:[a-zA-Z0-9-_]+""", r"""user_id:0 request:_snapshot_""", query)

        # ee license check has varying datetime
        # e.g. WHERE "ee_license"."valid_until" >= '2023-03-02T21:13:59.298031+00:00'::timestamptz
        query = re.sub(
            r"ee_license\"\.\"valid_until\" >= '\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d.\d{6}\+\d\d:\d\d'::timestamptz",
            '"ee_license"."valid_until">=\'LICENSE-TIMESTAMP\'::timestamptz"',
            query,
        )

        # insight cache key varies with team id
        query = re.sub(
            r"WHERE \(\"posthog_insightcachingstate\".\"cache_key\" = 'cache_\w{32}'",
            """WHERE ("posthog_insightcachingstate"."cache_key" = 'cache_THE_CACHE_KEY'""",
            query,
        )

        # replace Savepoint numbers
        query = re.sub(r"SAVEPOINT \".+\"", "SAVEPOINT _snapshot_", query)

        # test_formula has some values that change on every run
        query = re.sub(r"\SELECT \[\d+, \d+] as breakdown_value", "SELECT [1, 2] as breakdown_value", query)
        query = re.sub(
            r"SELECT distinct_id,[\n\r\s]+\d+ as value",
            "SELECT distinct_id, 1 as value",
            query,
        )

        assert sqlparse.format(query, reindent=True) == self.snapshot, "\n".join(self.snapshot.get_assert_diff())
        if params is not None:
            del params["team_id"]  # Changes every run
            assert params == self.snapshot, "\n".join(self.snapshot.get_assert_diff())


@contextmanager
def snapshot_postgres_queries_context(
    testcase: QueryMatchingTest,
    replace_all_numbers: bool = True,
    using: str = "default",
    capture_all_queries: bool = False,
):
    """
    Captures and snapshots select queries from test using `syrupy` library.
    Requires queries to be stable to avoid flakiness.

    Snapshots are automatically saved in a __snapshot__/*.ambr file.
    Update snapshots via --snapshot-update.

    To avoid flakiness, we optionally replaces all numbers in the query with a
    fixed output.

    Returns a context manager that can be used to capture queries.

    NOTE: it requires specifically that a `QueryMatchingTest` is used as the
    testcase argument.

    TODO: remove requirement that this must be used in conjunction with a
    `QueryMatchingTest` class.

    Example usage:

    class MyTest(QueryMatchingTest):
        def test_something(self):
            with snapshot_postgres_queries_context(self) as context:
                # Run some code that generates queries

    """
    with CaptureQueriesContext(connections[using]) as context:
        yield context

    for query_with_time in context.captured_queries:
        query = query_with_time["sql"]
        if capture_all_queries:
            testcase.assertQueryMatchesSnapshot(query, replace_all_numbers=replace_all_numbers)
        elif query and "SELECT" in query and "django_session" not in query and not re.match(r"^\s*INSERT", query):
            testcase.assertQueryMatchesSnapshot(query, replace_all_numbers=replace_all_numbers)


def snapshot_postgres_queries(fn):
    """
    Decorator that captures and snapshots select queries from test using
    `syrupy` library. It wraps `snapshot_postgres_queries_context`, see that
    context manager for more details.

    Example usage:

    class MyTest(QueryMatchingTest):
        @snapshot_postgres_queries
        def test_something(self):
            # Run some code that generates queries

    """

    @wraps(fn)
    def wrapped(self: QueryMatchingTest, *args, **kwargs):
        with snapshot_postgres_queries_context(self):
            fn(self, *args, **kwargs)

    return wrapped


class BaseTestMigrations(QueryMatchingTest):
    @property
    def app(self) -> str:
        return apps.get_containing_app_config(type(self).__module__).name  # type: ignore

    migrate_from: str
    migrate_to: str
    apps = None
    assert_snapshots = False

    def setUp(self):
        assert hasattr(self, "migrate_from") and hasattr(
            self, "migrate_to"
        ), "TestCase '{}' must define migrate_from and migrate_to properties".format(type(self).__name__)
        migrate_from = [(self.app, self.migrate_from)]
        migrate_to = [(self.app, self.migrate_to)]
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(migrate_from).apps

        # Reverse to the original migration
        executor.migrate(migrate_from)  # type: ignore

        self.setUpBeforeMigration(old_apps)

        # Run the migration to test
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()  # reload.

        if self.assert_snapshots:
            self._execute_migration_with_snapshots(executor)
        else:
            executor.migrate(migrate_to)  # type: ignore

        self.apps = executor.loader.project_state(migrate_to).apps

    @snapshot_postgres_queries
    def _execute_migration_with_snapshots(self, executor):
        migrate_to = [(self.app, self.migrate_to)]
        executor.migrate(migrate_to)

    def setUpBeforeMigration(self, apps):
        pass


class TestMigrations(BaseTestMigrations, BaseTest):
    """
    Can be used to test migrations
    """


class NonAtomicTestMigrations(BaseTestMigrations, NonAtomicBaseTest):
    """
    Can be used to test migrations where atomic=False.
    """


def flush_persons_and_events():
    person_mapping = {}
    if len(persons_cache_tests) > 0:
        person_mapping = bulk_create_persons(persons_cache_tests)
        persons_cache_tests.clear()
    if len(events_cache_tests) > 0:
        bulk_create_events(events_cache_tests, person_mapping)
        events_cache_tests.clear()


def _create_event(**kwargs):
    """
    Create an event in tests.

    Timezone support works as follows here:
    If a `timestamp` kwarg WITHOUT an explicit timezone is provided, it's treated as local to the project.
    Example: With the default `team.timezone = 'UTC'`, timestamp `2022-11-24T12:00:00` is saved verbatim to the DB,
    as all our stored data is in UTC . However, with `team.timezone = 'America/Phoenix'`, the event will in fact be
    stored with timestamp `2022-11-24T19:00:00` - because America/Pheonix is UTC-7, and Phoenix noon occurs at 7 PM UTC.
    If a `timestamp` WITH an explicit timezone is provided (in the case of ISO strings, this can be the "Z" suffix
    signifying UTC), we use that timezone instead of the project timezone.
    If NO `timestamp` is provided, we use the current system time (which can be mocked with `freeze_time()`)
    and treat that as local to the project.

    NOTE: All events get batched and only created when sync_execute is called.
    """
    if not kwargs.get("event_uuid"):
        kwargs["event_uuid"] = str(uuid.uuid4())
    if not kwargs.get("timestamp"):
        kwargs["timestamp"] = dt.datetime.now()
    events_cache_tests.append(kwargs)
    return kwargs["event_uuid"]


def _create_person(*args, **kwargs):
    """
    Create a person in tests. NOTE: all persons get batched and only created when sync_execute is called
    Pass immediate=True to create immediately and get a pk back
    """
    global persons_ordering_int
    if not (kwargs.get("uuid")):
        kwargs["uuid"] = uuid.UUID(
            int=persons_ordering_int, version=4
        )  # make sure the ordering of uuids is always consistent
    persons_ordering_int += 1
    # If we've done freeze_time just create straight away
    if kwargs.get("immediate") or (
        hasattr(dt.datetime.now(), "__module__") and dt.datetime.now().__module__ == "freezegun.api"
    ):
        if kwargs.get("immediate"):
            del kwargs["immediate"]
        create_person(
            team_id=kwargs.get("team_id") or kwargs["team"].pk,
            properties=kwargs.get("properties"),
            uuid=kwargs["uuid"],
            version=kwargs.get("version", 0),
        )
        return Person.objects.create(**kwargs)
    if len(args) > 0:
        kwargs["distinct_ids"] = [args[0]]  # allow calling _create_person("distinct_id")

    persons_cache_tests.append(kwargs)
    return Person(**{key: value for key, value in kwargs.items() if key != "distinct_ids"})


class ClickhouseTestMixin(QueryMatchingTest):
    RUN_MATERIALIZED_COLUMN_TESTS = True
    # overrides the basetest in posthog/test/base.py
    # this way the team id will increment so we don't have to destroy all clickhouse tables on each test
    CLASS_DATA_LEVEL_SETUP = False

    snapshot: Any

    def capture_select_queries(self):
        return self.capture_queries(("SELECT", "WITH", "select", "with"))

    @contextmanager
    def capture_queries(self, query_prefixes: Union[str, Tuple[str, ...]]):
        queries = []
        original_get_client = ch_pool.get_client

        # Spy on the `clichhouse_driver.Client.execute` method. This is a bit of
        # a roundabout way to handle this, but it seems tricky to spy on the
        # unbound class method `Client.execute` directly easily
        @contextmanager
        def get_client():
            with original_get_client() as client:
                original_client_execute = client.execute

                def execute_wrapper(query, *args, **kwargs):
                    if sqlparse.format(query, strip_comments=True).strip().startswith(query_prefixes):
                        queries.append(query)
                    return original_client_execute(query, *args, **kwargs)

                with patch.object(client, "execute", wraps=execute_wrapper) as _:
                    yield client

        with patch("posthog.clickhouse.client.connection.ch_pool.get_client", wraps=get_client) as _:
            yield queries


@contextmanager
def failhard_threadhook_context():
    """
    Context manager to ensure that exceptions raised by threads are treated as a
    test failure.
    """

    def raise_hook(args: threading.ExceptHookArgs):
        if args.exc_value is not None:
            raise args.exc_type(args.exc_value)

    old_hook, threading.excepthook = threading.excepthook, raise_hook
    try:
        yield old_hook
    finally:
        assert threading.excepthook is raise_hook
        threading.excepthook = old_hook


def run_clickhouse_statement_in_parallel(statements: List[str]):
    jobs = []
    with failhard_threadhook_context():
        for item in statements:
            thread = threading.Thread(target=sync_execute, args=(item,))
            jobs.append(thread)

        # Start the threads (i.e. calculate the random number lists)
        for j in jobs:
            j.start()

        # Ensure all of the threads have finished
        for j in jobs:
            j.join()


class ClickhouseDestroyTablesMixin(BaseTest):
    """
    To speed up tests we normally don't destroy the tables between tests, so clickhouse tables will have data from previous tests.
    Use this mixin to make sure you completely destroy the tables between tests.
    """

    def setUp(self):
        super().setUp()
        run_clickhouse_statement_in_parallel(
            [
                DROP_EVENTS_TABLE_SQL(),
                DROP_PERSON_TABLE_SQL,
                TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
                TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
                DROP_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                DROP_SESSION_REPLAY_EVENTS_TABLE_SQL(),
                TRUNCATE_GROUPS_TABLE_SQL,
                TRUNCATE_COHORTPEOPLE_TABLE_SQL,
                TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
                TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL,
            ]
        )
        run_clickhouse_statement_in_parallel(
            [
                EVENTS_TABLE_SQL(),
                PERSONS_TABLE_SQL(),
                SESSION_RECORDING_EVENTS_TABLE_SQL(),
                SESSION_REPLAY_EVENTS_TABLE_SQL(),
            ]
        )
        run_clickhouse_statement_in_parallel(
            [
                DISTRIBUTED_EVENTS_TABLE_SQL(),
                DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
            ]
        )

    def tearDown(self):
        super().tearDown()

        run_clickhouse_statement_in_parallel(
            [
                DROP_EVENTS_TABLE_SQL(),
                DROP_PERSON_TABLE_SQL,
                TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
                DROP_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                DROP_SESSION_REPLAY_EVENTS_TABLE_SQL(),
            ]
        )

        run_clickhouse_statement_in_parallel(
            [
                EVENTS_TABLE_SQL(),
                PERSONS_TABLE_SQL(),
                SESSION_RECORDING_EVENTS_TABLE_SQL(),
                SESSION_REPLAY_EVENTS_TABLE_SQL(),
            ]
        )
        run_clickhouse_statement_in_parallel(
            [
                DISTRIBUTED_EVENTS_TABLE_SQL(),
                DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
            ]
        )


def snapshot_clickhouse_queries(fn):
    """
    Captures and snapshots SELECT queries from test using `syrupy` library.

    Requires queries to be stable to avoid flakiness.

    Snapshots are automatically saved in a __snapshot__/*.ambr file.
    Update snapshots via --snapshot-update.
    """

    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.capture_select_queries() as queries:
            fn(self, *args, **kwargs)

        for query in queries:
            if "FROM system.columns" not in query:
                self.assertQueryMatchesSnapshot(query)

    return wrapped


def snapshot_clickhouse_alter_queries(fn):
    """
    Captures and snapshots ALTER queries from test using `syrupy` library.
    """

    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.capture_queries("ALTER") as queries:
            fn(self, *args, **kwargs)

        for query in queries:
            if "FROM system.columns" not in query:
                self.assertQueryMatchesSnapshot(query)

    return wrapped


def snapshot_clickhouse_insert_cohortpeople_queries(fn):
    """
    Captures and snapshots INSERT queries from test using `syrupy` library.
    """

    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.capture_queries("INSERT INTO cohortpeople") as queries:
            fn(self, *args, **kwargs)

        for query in queries:
            if "FROM system.columns" not in query:
                self.assertQueryMatchesSnapshot(query)

    return wrapped


def also_test_with_different_timezones(fn):
    """
    Runs the test thrice: 1. with UTC as the project timezone, 2. with UTC-7, 3. with UTC+9.
    This is intended for catching bugs around timezone handling.
    """

    def fn_minus_utc(self, *args, **kwargs):
        self.team.timezone = "America/Phoenix"  # UTC-7. Arizona does not observe DST, which is good for determinism
        self.team.save()
        fn(self, *args, **kwargs)

    def fn_plus_utc(self, *args, **kwargs):
        self.team.timezone = "Asia/Tokyo"  # UTC+9. Japan does not observe DST, which is good for determinism
        self.team.save()
        fn(self, *args, **kwargs)

    # To add the test, we inspect the frame this function was called in and add the test there
    frame_locals: Any = inspect.currentframe().f_back.f_locals  # type: ignore
    frame_locals[f"{fn.__name__}_minus_utc"] = fn_minus_utc
    frame_locals[f"{fn.__name__}_plus_utc"] = fn_plus_utc

    return fn


def also_test_with_person_on_events_v2(fn):
    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def fn_with_poe_v2(self, *args, **kwargs):
        fn(self, *args, **kwargs)

    # To add the test, we inspect the frame this function was called in and add the test there
    frame_locals: Any = inspect.currentframe().f_back.f_locals  # type: ignore
    frame_locals[f"{fn.__name__}_poe_v2"] = fn_with_poe_v2

    return fn


def _create_insight(
    team: Team, insight_filters: Dict[str, Any], dashboard_filters: Dict[str, Any]
) -> Tuple[Insight, Dashboard, DashboardTile]:
    dashboard = Dashboard.objects.create(team=team, filters=dashboard_filters)
    insight = Insight.objects.create(team=team, filters=insight_filters)
    dashboard_tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
    return insight, dashboard, dashboard_tile


# Populate the person_overrides table with an override from the person_id
# for a person with a given distinct ID `distinct_id_from` to a given distinct ID
# `distinct_id_to` such that with person_on_events_mode set to V2_ENABLED these
# persons will both count as 1
def create_person_id_override_by_distinct_id(
    distinct_id_from: str, distinct_id_to: str, team_id: int, version: int = 0
):
    person_ids_result = sync_execute(
        f"""
        SELECT distinct_id, person_id
        FROM events
        WHERE team_id = {team_id} AND distinct_id IN ('{distinct_id_from}', '{distinct_id_to}')
        GROUP BY distinct_id, person_id
        ORDER BY if(distinct_id = '{distinct_id_from}', -1, 0)
    """
    )

    person_id_from, person_id_to = [row[1] for row in person_ids_result]

    sync_execute(
        f"""
        INSERT INTO person_overrides (team_id, old_person_id, override_person_id, version)
        VALUES ({team_id}, '{person_id_from}', '{person_id_to}', {version})
    """
    )
