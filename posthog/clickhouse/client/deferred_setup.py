import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from django.conf import settings


class DeferredSetup:
    """Holds the test harness's ClickHouse setup until the process first uses ClickHouse.

    Test sessions that never query ClickHouse can then run while ClickHouse is down. Outside tests
    nothing calls defer(), so run() returns after one attribute check.
    """

    def __init__(self) -> None:
        self._setup: Callable[[], None] | None = None
        self._clickhouse_settings: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._owner: int | None = None
        self._worker = threading.local()
        self.has_run = False

    @property
    def is_pending(self) -> bool:
        return self._setup is not None

    def defer(self, setup: Callable[[], None]) -> None:
        with self._lock:
            self._setup = setup
            # A test can change ClickHouse settings before its first query, for example to fake
            # credentials, so the setup runs with the settings the session started with.
            self._clickhouse_settings = {
                name: getattr(settings, name) for name in dir(settings) if name.startswith("CLICKHOUSE_")
            }
            self.has_run = False

    def in_setup(self) -> bool:
        """True in the thread that runs the setup and in the DDL workers it starts."""
        return self._owner is not None and (
            self._owner == threading.get_ident() or getattr(self._worker, "active", False)
        )

    @contextmanager
    def worker(self, joins_setup: bool) -> Iterator[None]:
        """Let a thread that the setup started query ClickHouse before the setup finishes."""
        self._worker.active = joins_setup
        try:
            yield
        finally:
            self._worker.active = False

    def _pending(self) -> Callable[[], None] | None:
        return self._setup

    def run(self) -> None:
        while self._setup is not None and not self.in_setup():
            with self._lock:
                setup = self._pending()
                if setup is None:
                    return
                wait_for_other_thread = self._owner is not None
                if not wait_for_other_thread:
                    self._owner = threading.get_ident()
                    self._finished.clear()
            if wait_for_other_thread:
                # A failed setup stays pending, so the next pass retries it here and raises its error
                # instead of letting this caller query an incomplete schema.
                self._finished.wait()
                continue
            self._run_owned(setup)
            return

    def _run_owned(self, setup: Callable[[], None]) -> None:
        from django.test import override_settings  # noqa: PLC0415 (test-only code stays out of production imports)

        try:
            with override_settings(**self._clickhouse_settings):
                setup()
            # A failed setup stays pending, so each later test that needs ClickHouse shows the same error.
            self._setup = None
            self.has_run = True
        finally:
            self._owner = None
            self._finished.set()


clickhouse_test_setup = DeferredSetup()
