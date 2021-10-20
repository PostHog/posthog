from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS

from ee.conftest import reset_clickhouse_tables
from posthog.test.base import BaseTest


class ClickhouseTestMixin:
    RUN_MATERIALIZED_COLUMN_TESTS = True
    # overrides the basetest in posthog/test/base.py
    #  this way the team id will increment so we don't have to destroy all clickhouse tables on each test
    CLASS_DATA_LEVEL_SETUP = False

    @contextmanager
    def _assertNumQueries(self, func):
        yield

    # Ignore assertNumQueries in clickhouse tests
    def assertNumQueries(self, num, func=None, *args, using=DEFAULT_DB_ALIAS, **kwargs):
        return self._assertNumQueries(func)

    @contextmanager
    def capture_select_queries(self):
        # It's hard to spy on the right clients with test parallelization
        raise NotImplementedError()


class ClickhouseDestroyTablesMixin(BaseTest):
    """
    To speed up tests we normally don't destroy the tables between tests, so clickhouse tables will have data from previous tests.
    Use this mixin to make sure you completely destroy the tables between tests.
    """

    def setUp(self):
        super().setUp()
        reset_clickhouse_tables()

    def tearDown(self):
        super().tearDown()
        reset_clickhouse_tables()
