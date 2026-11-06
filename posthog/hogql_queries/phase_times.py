RATE_LIMITERS_KEY = "./rate_limiters"
CACHE_WRITE_KEY = "./cache_write"
FLIGHT_WAIT_KEY = "./flight_wait"


def _node_ms(runner_timings: dict[str, float], before: dict[str, float], key: str) -> float | None:
    seconds = runner_timings.get(key)
    if seconds is None or seconds == before.get(key):
        return None
    return round((seconds - before.get(key, 0.0)) * 1000, 2)


def compute_phase_times(
    runner_timings: dict[str, float], before: dict[str, float] | None = None
) -> dict[str, float | None]:
    """The phases a run spends outside the calculation, read off the runner's ``HogQLTimings`` tree
    (``self.timings.to_dict()``, seconds per node) for the ``query executed`` event.

    ``rate_limiters_ms`` is the wait to acquire the concurrency limiters, ``cache_write_ms`` the time
    to store the result, ``flight_wait_ms`` a single-flight follower's wait for the leader. Each is
    ``None`` when the run did not pass through that phase. Milliseconds, two decimals. ``before`` is
    the same tree as it stood when the run started: the tree adds up across runs of one runner, so
    the difference is this run's own time. ClickHouse time is not derived here: the stats scope
    already puts it on the event as ``clickhouse_duration_ms``.
    """
    before = before or {}
    return {
        "rate_limiters_ms": _node_ms(runner_timings, before, RATE_LIMITERS_KEY),
        "cache_write_ms": _node_ms(runner_timings, before, CACHE_WRITE_KEY),
        "flight_wait_ms": _node_ms(runner_timings, before, FLIGHT_WAIT_KEY),
    }
