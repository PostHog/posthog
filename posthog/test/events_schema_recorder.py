"""Records which tests reach the native-JSON events tables during an events_json run.

A test that never prints or sends SQL that names an events_json table reads the same tables and
rows under both events schemas, so the events_json CI leg learns nothing new by running it.
"""

import re
import json
import functools
from collections import Counter, defaultdict
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest

from django.conf import settings

import clickhouse_driver

import posthog.hogql.database.schema.events as hogql_events_schema

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ProxyClient
from posthog.clickhouse.events_json import (
    DISTRIBUTED_EVENTS_JSON_TABLE,
    EVENTS_JSON_DATA_TABLE,
    WRITABLE_EVENTS_JSON_TABLE,
)
from posthog.temporal.common.clickhouse import ClickHouseClient as AsyncClickHouseClient

EVENTS_JSON_TABLES = (DISTRIBUTED_EVENTS_JSON_TABLE, EVENTS_JSON_DATA_TABLE, WRITABLE_EVENTS_JSON_TABLE)
EVENTS_JSON_TABLE_NAME = re.compile(rf"(?<!\w)(?:{'|'.join(EVENTS_JSON_TABLES)})(?!\w)")
# In this mode the event fixtures also insert every event into the JSON table. Only a read or a
# mutation of that table can change what a test sees, so the fixture insert and the table setup and
# cleanup statements do not count.
FIXTURE_INSERT_MARKER = "JSONCleanPostHogTemporaryProperties(source.c3) FROM values("
SETUP_STATEMENT = re.compile(r"\s*(?:CREATE|DROP|TRUNCATE)\b", re.IGNORECASE)


def names_events_json_table(sql: str) -> bool:
    if FIXTURE_INSERT_MARKER in sql or SETUP_STATEMENT.match(sql):
        return False
    return EVENTS_JSON_TABLE_NAME.search(sql) is not None


class EventsSchemaRecorder:
    def __init__(self, output: Path) -> None:
        self._output = output
        self._nodeid: str | None = None
        self._phase = "setup"
        self._hits: dict[str, Counter[str]] = {}
        self._seconds: defaultdict[str, float] = defaultdict(float)
        self._outcomes: dict[str, str] = {}
        self._ran_clickhouse = False
        self._json_table_readers: list[str] | None = None
        self._install()

    def _install(self) -> None:
        for owner, name in (
            (clickhouse_driver.Client, "execute"),
            (clickhouse_driver.Client, "execute_iter"),
            (clickhouse_driver.Client, "execute_with_progress"),
            (ProxyClient, "execute"),
            (AsyncClickHouseClient, "prepare_query"),
        ):
            setattr(owner, name, self._observe_sql(getattr(owner, name)))
        # Only the events schema module calls this helper, and it looks the name up on each call.
        table_ref = hogql_events_schema.events_table_clickhouse_table_ref

        def observed_table_ref(context: Any) -> str:
            printed = table_ref(context)
            if printed == DISTRIBUTED_EVENTS_JSON_TABLE:
                self._hit()
            return printed

        hogql_events_schema.events_table_clickhouse_table_ref = observed_table_ref  # ty: ignore[invalid-assignment]

    def _observe_sql(self, method: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(method)
        def observed(client: Any, query: Any = None, *args: Any, **kwargs: Any) -> Any:
            self._ran_clickhouse = True
            if isinstance(query, str) and names_events_json_table(query):
                self._hit()
            return method(client, query, *args, **kwargs)

        return observed

    def _hit(self) -> None:
        if self._nodeid is not None:
            self._hits.setdefault(self._nodeid, Counter())[self._phase] += 1

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> Generator[None]:
        self._nodeid, self._phase = item.nodeid, "setup"
        return (yield)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item: pytest.Item) -> Generator[None]:
        self._phase = "call"
        return (yield)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_teardown(self, item: pytest.Item) -> Generator[None]:
        self._phase = "teardown"
        try:
            return (yield)
        finally:
            self._nodeid = None

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self._seconds[report.nodeid] += report.duration
        if report.when == "call" or report.outcome != "passed":
            self._outcomes[report.nodeid] = report.outcome

    def pytest_runtest_logfinish(self, nodeid: str) -> None:
        if self._ran_clickhouse and self._json_table_readers is None:
            self._json_table_readers = self._find_json_table_readers()

    def _find_json_table_readers(self) -> list[str]:
        # A view that reads the JSON tables would copy fixture rows into other tables, where the
        # SQL check cannot see them. A recording that lists a reader cannot prove any test independent.
        try:
            rows = sync_execute(
                "SELECT name, dependencies_table FROM system.tables WHERE database = currentDatabase() AND name IN %(tables)s",
                {"tables": EVENTS_JSON_TABLES},
            )
        except Exception as error:
            return [f"check failed: {error}"]
        return sorted({f"{table} -> {reader}" for table, readers in rows for reader in readers})

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        tests = {
            nodeid: {
                "hits": dict(self._hits.get(nodeid, {})),
                "seconds": round(seconds, 3),
                "outcome": self._outcomes.get(nodeid, "passed"),
            }
            for nodeid, seconds in self._seconds.items()
        }
        self._output.write_text(
            json.dumps(
                {
                    "events_json_mode": settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA,
                    "json_table_readers": self._json_table_readers,
                    "tests": tests,
                },
                indent=1,
                sort_keys=True,
            )
        )
