from contextlib import contextmanager
from typing import List
from unittest.mock import patch

from django.db import DEFAULT_DB_ALIAS


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
        from ee.clickhouse.client import _annotate_tagged_query

        sqls: List[str] = []

        def wrapped_method(*args):
            if args[0].strip().startswith("SELECT"):
                sqls.append(args[0])
            return _annotate_tagged_query(*args)

        with patch("ee.clickhouse.client._annotate_tagged_query", wraps=wrapped_method) as wrapped_annotate:
            yield sqls
