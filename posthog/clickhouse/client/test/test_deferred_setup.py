import threading
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

from posthog.clickhouse.client.deferred_setup import DeferredSetup


class _ArrivalSignalingEvent(threading.Event):
    def __init__(self) -> None:
        super().__init__()
        self.waiter_arrived = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        self.waiter_arrived.set()
        return super().wait(timeout)


def _deferred_that_signals_waiters() -> tuple[DeferredSetup, _ArrivalSignalingEvent]:
    deferred = DeferredSetup()
    finished = _ArrivalSignalingEvent()
    deferred._finished = finished
    return deferred, finished


def test_a_concurrent_first_use_waits_until_the_setup_finished() -> None:
    deferred, finished = _deferred_that_signals_waiters()
    setup_started = threading.Event()
    release_setup = threading.Event()
    seen_by_other_thread: list[bool] = []

    def setup() -> None:
        setup_started.set()
        release_setup.wait(timeout=5)

    def other_thread() -> None:
        setup_started.wait(timeout=5)
        deferred.run()
        seen_by_other_thread.append(deferred.has_run)

    deferred.defer(setup)
    waiter = threading.Thread(target=other_thread)
    waiter.start()
    owner = threading.Thread(target=deferred.run)
    owner.start()
    setup_started.wait(timeout=5)
    assert finished.waiter_arrived.wait(timeout=5)
    release_setup.set()
    owner.join(timeout=5)
    waiter.join(timeout=5)

    assert seen_by_other_thread == [True]


def test_the_setup_workers_query_without_waiting_for_the_setup() -> None:
    deferred = DeferredSetup()
    worker_results: list[bool] = []

    def setup() -> None:
        joins_setup = deferred.in_setup()

        def worker() -> None:
            with deferred.worker(joins_setup):
                deferred.run()
                worker_results.append(deferred.in_setup())

        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in [pool.submit(worker) for _ in range(2)]:
                future.result(timeout=5)

    deferred.defer(setup)
    deferred.run()

    assert worker_results == [True, True]
    assert deferred.has_run


def test_the_setup_uses_the_clickhouse_settings_of_the_session_start() -> None:
    deferred = DeferredSetup()
    seen: list[str] = []
    deferred.defer(lambda: seen.append(settings.CLICKHOUSE_USER))
    original_user = settings.CLICKHOUSE_USER

    settings.CLICKHOUSE_USER = "a-test-fake-user"
    try:
        deferred.run()
    finally:
        settings.CLICKHOUSE_USER = original_user

    assert seen == [original_user]


def test_a_failed_setup_stays_pending() -> None:
    deferred = DeferredSetup()
    attempts: list[int] = []

    def setup() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("ClickHouse is down")

    deferred.defer(setup)
    try:
        deferred.run()
    except ConnectionError:
        pass
    deferred.run()

    assert (len(attempts), deferred.has_run, deferred.is_pending) == (2, True, False)


def test_a_waiting_caller_retries_a_setup_that_failed() -> None:
    deferred, finished = _deferred_that_signals_waiters()
    setup_started = threading.Event()
    release_setup = threading.Event()
    attempts: list[str] = []
    errors: list[Exception] = []

    def setup() -> None:
        attempts.append(threading.current_thread().name)
        if len(attempts) == 1:
            setup_started.set()
            release_setup.wait(timeout=5)
            raise ConnectionError("ClickHouse is down")

    def owner() -> None:
        try:
            deferred.run()
        except ConnectionError as error:
            errors.append(error)

    deferred.defer(setup)
    first = threading.Thread(target=owner, name="owner")
    first.start()
    setup_started.wait(timeout=5)
    waiter = threading.Thread(target=deferred.run, name="waiter")
    waiter.start()
    assert finished.waiter_arrived.wait(timeout=5)
    release_setup.set()
    first.join(timeout=5)
    waiter.join(timeout=5)

    assert attempts == ["owner", "waiter"]
    assert len(errors) == 1
    assert deferred.has_run
