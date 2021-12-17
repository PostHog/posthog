from contextlib import contextmanager
from functools import wraps
from typing import Any
from unittest.mock import patch

import sqlparse
from django.db import DEFAULT_DB_ALIAS

from ee.clickhouse.client import ch_pool, sync_execute
from ee.clickhouse.sql.events import DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
from ee.clickhouse.sql.person import DROP_PERSON_TABLE_SQL, PERSONS_TABLE_SQL, TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL
from ee.clickhouse.sql.session_recording_events import (
    DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
)
from posthog.test.base import BaseTest, QueryMatchingTest


class ClickhouseTestMixin(QueryMatchingTest):
    RUN_MATERIALIZED_COLUMN_TESTS = True
    # overrides the basetest in posthog/test/base.py
    #  this way the team id will increment so we don't have to destroy all clickhouse tables on each test
    CLASS_DATA_LEVEL_SETUP = False

    snapshot: Any

    @contextmanager
    def _assertNumQueries(self, func):
        yield

    # Ignore assertNumQueries in clickhouse tests
    def assertNumQueries(self, num, func=None, *args, using=DEFAULT_DB_ALIAS, **kwargs):
        return self._assertNumQueries(func)

    @contextmanager
    def capture_select_queries(self):
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
                    if sqlparse.format(query, strip_comments=True).strip().startswith(("SELECT", "WITH")):
                        queries.append(query)
                    return original_client_execute(query, *args, **kwargs)

                with patch.object(client, "execute", wraps=execute_wrapper) as _:
                    yield client

        with patch("ee.clickhouse.client.ch_pool.get_client", wraps=get_client) as _:
            yield queries


class ClickhouseDestroyTablesMixin(BaseTest):
    """
    To speed up tests we normally don't destroy the tables between tests, so clickhouse tables will have data from previous tests.
    Use this mixin to make sure you completely destroy the tables between tests.
    """

    def setUp(self):
        super().setUp()
        sync_execute(DROP_EVENTS_TABLE_SQL)
        sync_execute(EVENTS_TABLE_SQL())
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL)
        sync_execute(PERSONS_TABLE_SQL())
        sync_execute(DROP_SESSION_RECORDING_EVENTS_TABLE_SQL)
        sync_execute(SESSION_RECORDING_EVENTS_TABLE_SQL())
        sync_execute(SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL)

    def tearDown(self):
        super().tearDown()
        sync_execute(DROP_EVENTS_TABLE_SQL)
        sync_execute(EVENTS_TABLE_SQL())
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL)
        sync_execute(PERSONS_TABLE_SQL())
        sync_execute(DROP_SESSION_RECORDING_EVENTS_TABLE_SQL)
        sync_execute(SESSION_RECORDING_EVENTS_TABLE_SQL())
        sync_execute(SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL)


def snapshot_clickhouse_queries(fn):
    """
    Captures and snapshots select queries from test using `syrupy` library.

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
