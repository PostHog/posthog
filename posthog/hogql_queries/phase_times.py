RATE_LIMITERS_KEY = "./rate_limiters"
CACHE_WRITE_KEY = "./cache_write"
FLIGHT_WAIT_KEY = "./flight_wait"
# QueryRunner.shared_database measures the build under this name, inside whichever phase first needed the database.
BUILD_DATABASE_NODE = "build_shared_database"


def _node_ms(runner_timings: dict[str, float], before: dict[str, float], key: str) -> float | None:
    seconds = runner_timings.get(key)
    if seconds is None or seconds == before.get(key):
        return None
    return round((seconds - before.get(key, 0.0)) * 1000, 2)


def _nodes_named_ms(runner_timings: dict[str, float], before: dict[str, float], name: str) -> float | None:
    added = [
        ms
        for key in runner_timings
        if key.rsplit("/", 1)[-1] == name and (ms := _node_ms(runner_timings, before, key)) is not None
    ]
    return round(sum(added), 2) if added else None


def compute_phase_times(
    runner_timings: dict[str, float], before: dict[str, float] | None = None
) -> dict[str, float | None]:
    """The phases a run spends outside the calculation, read off the runner's ``HogQLTimings`` tree
    (``self.timings.to_dict()``, seconds per node) for the ``query executed`` event.

    ``rate_limiters_ms`` is the wait to acquire the concurrency limiters, ``cache_write_ms`` the time
    to store the result, ``flight_wait_ms`` a single-flight follower's wait for the leader, and
    ``build_database_ms`` the time ``QueryRunner.shared_database`` spent building the HogQL database.
    Each is ``None`` when the run did not pass through that phase, and also when the tree does not
    show it: a runner that clears its timings mid-run, a build on the shared-database kill-switch path
    (left unmeasured because ``HogQLTimings`` is not thread-safe), and a build outside
    ``shared_database``, such as ``execute_hogql_query`` called without a context. Milliseconds, two
    decimals. ``before`` is the same tree as it stood when the run started: the tree adds up across runs
    of one runner, so the difference is this run's own time. ClickHouse time is not derived here: the
    stats scope already puts it on the event as ``clickhouse_duration_ms``.
    """
    before = before or {}
    return {
        "rate_limiters_ms": _node_ms(runner_timings, before, RATE_LIMITERS_KEY),
        "cache_write_ms": _node_ms(runner_timings, before, CACHE_WRITE_KEY),
        "flight_wait_ms": _node_ms(runner_timings, before, FLIGHT_WAIT_KEY),
        "build_database_ms": _nodes_named_ms(runner_timings, before, BUILD_DATABASE_NODE),
    }
