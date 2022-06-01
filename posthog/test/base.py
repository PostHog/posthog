import inspect
import re
import uuid
from functools import wraps
from typing import Any, Dict, List, Optional

import pytest
import sqlparse
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now
from rest_framework.test import APITestCase as DRFTestCase

from posthog.models import Organization, Team, User
from posthog.models.event.util import bulk_create_events
from posthog.models.organization import OrganizationMembership
from posthog.models.person import Person
from posthog.models.person.util import bulk_create_persons, create_person

persons_cache_tests: List[Dict[str, Any]] = []
events_cache_tests: List[Dict[str, Any]] = []


def _setup_test_data(klass):
    klass.organization = Organization.objects.create(name=klass.CONFIG_ORGANIZATION_NAME)
    klass.team = Team.objects.create(
        organization=klass.organization,
        api_token=klass.CONFIG_API_TOKEN,
        test_account_filters=[
            {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
        ],
    )
    if klass.CONFIG_EMAIL:
        klass.user = User.objects.create_and_join(klass.organization, klass.CONFIG_EMAIL, klass.CONFIG_PASSWORD)
        klass.organization_membership = klass.user.organization_memberships.get()


class ErrorResponsesMixin:

    ERROR_INVALID_CREDENTIALS = {
        "type": "validation_error",
        "code": "invalid_credentials",
        "detail": "Invalid email or password.",
        "attr": None,
    }

    def not_found_response(self, message: str = "Not found.") -> Dict[str, Optional[str]]:
        return {
            "type": "invalid_request",
            "code": "not_found",
            "detail": message,
            "attr": None,
        }

    def permission_denied_response(
        self, message: str = "You do not have permission to perform this action.",
    ) -> Dict[str, Optional[str]]:
        return {
            "type": "authentication_error",
            "code": "permission_denied",
            "detail": message,
            "attr": None,
        }

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
        return {
            "type": "authentication_error",
            "code": code,
            "detail": message,
            "attr": None,
        }

    def validation_error_response(
        self, message: str = "Malformed request", code: str = "invalid_input", attr: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        return {
            "type": "validation_error",
            "code": code,
            "detail": message,
            "attr": attr,
        }


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

    def setUp(self):
        super().setUp()
        if self.CONFIG_AUTO_LOGIN and self.user:
            self.client.force_login(self.user)

    def assertEntityResponseEqual(self, response1, response2, remove=("action", "label", "persons_urls", "filter")):
        stripped_response1 = stripResponse(response1, remove=remove)
        stripped_response2 = stripResponse(response2, remove=remove)
        self.assertDictEqual(stripped_response1[0], stripped_response2[0])


def stripResponse(response, remove=("action", "label", "persons_urls", "filter")):
    if len(response):
        for attr in remove:
            if attr in response[0]:
                response[0].pop(attr)
    return response


def test_with_materialized_columns(event_properties=[], person_properties=[], verify_no_jsonextract=True):
    """
    Runs the test twice on clickhouse - once verifying it works normally, once with materialized columns.

    Requires a unittest class with ClickhouseTestMixin mixed in
    """

    try:
        from ee.clickhouse.materialized_columns import get_materialized_columns, materialize
        from posthog.client import sync_execute
    except:
        # EE not available? Just run the main test
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

            try:
                with self.capture_select_queries() as sqls:
                    fn(self, *args, **kwargs)
            finally:
                for prop in event_properties:
                    column_name = get_materialized_columns("events")[prop]
                    sync_execute(f"ALTER TABLE events DROP COLUMN {column_name}")
                for prop in person_properties:
                    column_name = get_materialized_columns("person")[prop]
                    sync_execute(f"ALTER TABLE person DROP COLUMN {column_name}")

            if verify_no_jsonextract:
                for sql in sqls:
                    self.assertNotIn("JSONExtract(properties", sql)

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
        else:
            query = re.sub(r"(team|cohort)_id(\"?) = \d+", r"\1_id\2 = 2", query)

        # Replace organization_id lookups, for postgres
        query = re.sub(
            fr"""("organization_id"|"posthog_organization"\."id") = '[^']+'::uuid""",
            r"""\1 = '00000000-0000-0000-0000-000000000000'::uuid""",
            query,
        )
        query = re.sub(
            fr"""("organization_id"|"posthog_organization"\."id") IN \('[^']+'::uuid\)""",
            r"""\1 IN ('00000000-0000-0000-0000-000000000000'::uuid)""",
            query,
        )

        # Replace tag id lookups for postgres
        query = re.sub(
            fr"""("posthog_tag"\."id") IN \(('[^']+'::uuid)+(, ('[^']+'::uuid)+)*\)""",
            r"""\1 IN ('00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid /* ... */)""",
            query,
        )

        assert sqlparse.format(query, reindent=True) == self.snapshot, "\n".join(self.snapshot.get_assert_diff())
        if params is not None:
            del params["team_id"]  # Changes every run
            assert params == self.snapshot, "\n".join(self.snapshot.get_assert_diff())


def snapshot_postgres_queries(fn):
    """
    Captures and snapshots select queries from test using `syrupy` library.

    Requires queries to be stable to avoid flakiness.

    Snapshots are automatically saved in a __snapshot__/*.ambr file.
    Update snapshots via --snapshot-update.
    """
    from django.db import connections

    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with CaptureQueriesContext(connections["default"]) as context:
            fn(self, *args, **kwargs)

        for query_with_time in context.captured_queries:
            query = query_with_time["sql"]
            if "SELECT" in query and "django_session" not in query:
                self.assertQueryMatchesSnapshot(query, replace_all_numbers=True)

    return wrapped


class BaseTestMigrations(QueryMatchingTest):
    @property
    def app(self):
        return apps.get_containing_app_config(type(self).__module__).name  # type: ignore

    migrate_from = None
    migrate_to = None
    apps = None
    assert_snapshots = False

    def setUp(self):
        assert (
            self.migrate_from and self.migrate_to  # type: ignore
        ), "TestCase '{}' must define migrate_from and migrate_to properties".format(type(self).__name__)
        self.migrate_from = [(self.app, self.migrate_from)]  # type: ignore
        self.migrate_to = [(self.app, self.migrate_to)]
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        # Reverse to the original migration
        executor.migrate(self.migrate_from)

        self.setUpBeforeMigration(old_apps)

        # Run the migration to test
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()  # reload.

        if self.assert_snapshots:
            self._execute_migration_with_snapshots(executor)
        else:
            executor.migrate(self.migrate_to)

        self.apps = executor.loader.project_state(self.migrate_to).apps

    @snapshot_postgres_queries
    def _execute_migration_with_snapshots(self, executor):
        executor.migrate(self.migrate_to)

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
    Create an event in tests. NOTE: all events get batched and only created when sync_execute is called
    """
    if not kwargs.get("event_uuid"):
        kwargs["event_uuid"] = str(uuid.uuid4())
    if not kwargs.get("timestamp"):
        kwargs["timestamp"] = now()
    events_cache_tests.append(kwargs)
    return kwargs["event_uuid"]


def _create_person(*args, **kwargs):
    """
    Create a person in tests. NOTE: all persons get batched and only created when sync_execute is called
    Pass immediate=True to create immediately and get a pk back
    """
    kwargs["uuid"] = uuid.uuid4()
    # If we've done freeze_time just create straight away
    if kwargs.get("immediate") or (hasattr(now(), "__module__") and now().__module__ == "freezegun.api"):
        if kwargs.get("immediate"):
            del kwargs["immediate"]
        create_person(
            team_id=kwargs.get("team_id") or kwargs["team"].pk, properties=kwargs.get("properties"), uuid=kwargs["uuid"]
        )
        return Person.objects.create(**kwargs)
    if len(args) > 0:
        kwargs["distinct_ids"] = [args[0]]  # allow calling _create_person("distinct_id")

    persons_cache_tests.append(kwargs)
    return Person(**{key: value for key, value in kwargs.items() if key != "distinct_ids"})
