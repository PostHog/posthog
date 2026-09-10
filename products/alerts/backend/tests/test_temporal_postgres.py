from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from unittest.mock import MagicMock, patch

from django.db import InterfaceError, OperationalError, ProgrammingError, connections
from django.test import override_settings

from temporalio.api.failure.v1 import Failure
from temporalio.converter import DefaultFailureConverter, DefaultPayloadConverter
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import ActivityEnvironment

from products.alerts.backend.temporal import postgres
from products.alerts.backend.temporal.workflows import POSTGRES_PROBE_FAILURE, alerts_product_check_due_activity

if TYPE_CHECKING:
    from pytest_django.fixtures import Settings


@pytest.mark.parametrize(
    "error",
    [
        None,
        OperationalError("sensitive connection details"),
        InterfaceError("sensitive connection details"),
        ProgrammingError("unrelated error"),
        CancelledError(),
        asyncio.CancelledError(),
    ],
)
async def test_probe_uses_database_thread_and_sanitizes_only_expected_errors(
    error: BaseException | None, settings: Settings
) -> None:
    settings.TEST = False
    threads: list[int] = []
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    cursor.execute.side_effect = error
    connection = MagicMock()
    connection.close.side_effect = lambda: threads.append(threading.get_ident())

    @contextmanager
    def execute_with_timeout(timeout: int, database: str) -> Iterator[MagicMock]:
        assert timeout == 1000
        assert database == "default"
        threads.append(threading.get_ident())
        try:
            yield cursor
        finally:
            threads.append(threading.get_ident())

    with (
        patch.object(postgres, "execute_with_timeout", execute_with_timeout),
        patch("django.db.connections.all", return_value=[connection]),
    ):
        environment = ActivityEnvironment()
        if error is None:
            await environment.run(alerts_product_check_due_activity)
            cursor.fetchone.assert_called_once_with()
        elif isinstance(error, (OperationalError, InterfaceError)):
            with pytest.raises(ApplicationError) as caught:
                await environment.run(alerts_product_check_due_activity)
            assert caught.value.type == POSTGRES_PROBE_FAILURE
            failure = Failure()
            DefaultFailureConverter().to_failure(caught.value, DefaultPayloadConverter(), failure)
            assert not failure.HasField("cause")
            assert "sensitive" not in str(failure)
        else:
            with pytest.raises(type(error)) as caught_unrelated:
                await environment.run(alerts_product_check_due_activity)
            assert caught_unrelated.value is error

    cursor.execute.assert_called_once_with("SELECT 1")
    assert len(threads) == 4
    assert len(set(threads)) == 1
    assert threads[0] != threading.get_ident()
    assert connection.close.call_count == 2
    connection.close_if_unusable_or_obsolete.assert_not_called()


async def test_probe_cancellation_and_concurrent_activity_cleanup(settings: Settings) -> None:
    settings.TEST = False
    entered = asyncio.Event()
    release = threading.Event()
    cleaned_up = threading.Event()
    loop = asyncio.get_running_loop()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    connection = MagicMock()
    cleanup_threads: list[int] = []

    def close() -> None:
        cleanup_threads.append(threading.get_ident())
        if cleanup_threads.count(cleanup_threads[0]) == 2:
            cleaned_up.set()

    connection.close.side_effect = close

    @contextmanager
    def execute_with_timeout(timeout: int, database: str) -> Iterator[MagicMock]:
        if not entered.is_set():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(timeout=10)
        yield cursor

    with (
        patch.object(postgres, "execute_with_timeout", execute_with_timeout),
        patch("django.db.connections.all", return_value=[connection]),
    ):
        task = asyncio.create_task(ActivityEnvironment().run(alerts_product_check_due_activity))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            await asyncio.wait_for(ActivityEnvironment().run(alerts_product_check_due_activity), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not cleaned_up.is_set()
        finally:
            release.set()
            assert await asyncio.to_thread(cleaned_up.wait, 5)
    assert len(cleanup_threads) == 4
    assert len(set(cleanup_threads)) == 2
    assert threading.get_ident() not in cleanup_threads


def test_probe_rejects_unexpected_result() -> None:
    with patch.object(postgres, "execute_with_timeout") as execute:
        execute.return_value.__enter__.return_value.fetchone.return_value = (0,)
        with pytest.raises(ValueError, match="Unexpected Postgres probe result"):
            postgres.check_postgres_connection()


@pytest.mark.django_db(transaction=True, databases=["default"], available_apps=[])
def test_probe_statement_timeout_rolls_back_and_closes_without_leaking() -> None:
    connection = connections["default"]
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        original_timeout = cursor.fetchone()
    statements: list[str] = []
    close_states: list[tuple[bool, bool]] = []
    original_close = connection.close

    def close() -> None:
        close_states.append((connection.in_atomic_block, connection.needs_rollback))
        if len(close_states) == 2:
            with connection.cursor() as cursor:
                cursor.execute("SHOW statement_timeout")
                assert cursor.fetchone() == original_timeout
                cursor.execute("SELECT 2")
                assert cursor.fetchone() == (2,)
        original_close()

    def slow_probe(
        execute: Callable[[str, object, bool, dict[str, object]], object],
        sql: str,
        params: object,
        many: bool,
        context: dict[str, object],
    ) -> object:
        statements.append(sql)
        if sql == "SELECT 1":
            assert connection.in_atomic_block
            with connection.cursor() as timeout_cursor:
                timeout_cursor.execute("SHOW statement_timeout")
                assert timeout_cursor.fetchone() == ("1s",)
            return execute("SELECT pg_sleep(2)", None, False, context)
        return execute(sql, params, many, context)

    with (
        override_settings(TEST=False),
        patch.object(connection, "close", close),
        patch.object(connection, "rollback", wraps=connection.rollback) as rollback,
    ):
        with connection.execute_wrapper(slow_probe), pytest.raises(OperationalError) as caught:
            postgres.check_postgres_connection()
        assert getattr(caught.value.__cause__, "sqlstate", None) == "57014"
        rollback.assert_called_once_with()
        assert connection.connection is None
        assert close_states == [(False, False), (False, False)]
        assert statements.count("SELECT 1") == 1
        with connection.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            assert cursor.fetchone() == original_timeout
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
        postgres.check_postgres_connection()
        assert connection.connection is None
