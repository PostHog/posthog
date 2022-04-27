from contextlib import contextmanager
from functools import wraps
from typing import Any, Tuple, Union
from unittest.mock import patch

import sqlparse

from ee.clickhouse.sql.events import DISTRIBUTED_EVENTS_TABLE_SQL, DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
from ee.clickhouse.sql.person import DROP_PERSON_TABLE_SQL, PERSONS_TABLE_SQL, TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL
from ee.clickhouse.sql.session_recording_events import (
    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
)
from posthog.client import ch_pool
from posthog.conftest import run_clickhouse_statement_in_parallel
from posthog.settings import CLICKHOUSE_REPLICATION
from posthog.test.base import BaseTest, QueryMatchingTest


class ClickhouseTestMixin(QueryMatchingTest):
    RUN_MATERIALIZED_COLUMN_TESTS = True
    # overrides the basetest in posthog/test/base.py
    #  this way the team id will increment so we don't have to destroy all clickhouse tables on each test
    CLASS_DATA_LEVEL_SETUP = False

    snapshot: Any

    def capture_select_queries(self):
        return self.capture_queries(("SELECT", "WITH",))

    @contextmanager
    def capture_queries(self, query_prefixes: Union[str, Tuple[str, str]]):
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

        with patch("posthog.client.ch_pool.get_client", wraps=get_client) as _:
            yield queries


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
                DROP_SESSION_RECORDING_EVENTS_TABLE_SQL(),
            ]
        )
        run_clickhouse_statement_in_parallel(
            [EVENTS_TABLE_SQL(), PERSONS_TABLE_SQL(), SESSION_RECORDING_EVENTS_TABLE_SQL(),]
        )
        if CLICKHOUSE_REPLICATION:
            run_clickhouse_statement_in_parallel(
                [DISTRIBUTED_EVENTS_TABLE_SQL(), DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL()]
            )

    def tearDown(self):
        super().tearDown()

        run_clickhouse_statement_in_parallel(
            [
                DROP_EVENTS_TABLE_SQL(),
                DROP_PERSON_TABLE_SQL,
                TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
                DROP_SESSION_RECORDING_EVENTS_TABLE_SQL(),
            ]
        )
        run_clickhouse_statement_in_parallel(
            [EVENTS_TABLE_SQL(), PERSONS_TABLE_SQL(), SESSION_RECORDING_EVENTS_TABLE_SQL(),]
        )
        if CLICKHOUSE_REPLICATION:
            run_clickhouse_statement_in_parallel(
                [DISTRIBUTED_EVENTS_TABLE_SQL(), DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL()]
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
