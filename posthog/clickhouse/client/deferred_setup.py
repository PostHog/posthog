from collections.abc import Callable


class DeferredSetup:
    """Holds the test harness's ClickHouse setup until the process first uses ClickHouse.

    Test sessions that never query ClickHouse can then run while ClickHouse is down. Outside tests
    nothing calls defer(), so run() returns after one attribute check.
    """

    def __init__(self) -> None:
        self._setup: Callable[[], None] | None = None
        self.has_run = False

    @property
    def is_pending(self) -> bool:
        return self._setup is not None

    def defer(self, setup: Callable[[], None]) -> None:
        self._setup = setup
        self.has_run = False

    def run(self) -> None:
        setup = self._setup
        if setup is None:
            return
        # The setup queries ClickHouse through the clients that call run(), so clear it first to stop the recursion.
        # A second thread that queries ClickHouse while the setup runs does not wait for it.
        self._setup = None
        try:
            setup()
        except BaseException:
            # Keep the setup pending, so that each later test that needs ClickHouse shows the same error.
            self._setup = setup
            raise
        self.has_run = True


clickhouse_test_setup = DeferredSetup()
