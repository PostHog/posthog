from datetime import timedelta
from typing import Tuple
from uuid import uuid4

from freezegun import freeze_time

from posthog.clickhouse.client.rate_limiter import RateLimiter


def simulate_requests(rl: RateLimiter, requests: int, key: str) -> Tuple[int, int]:
    limit = 10
    period = timedelta(minutes=1)

    good_calls = 0
    bad_calls = 0

    for _ in range(requests):
        if rl.request_is_limited(key, limit, period):
            bad_calls += 1
        else:
            good_calls += 1
    return (good_calls, bad_calls)


def test_basic_rate_limiting():
    rl = RateLimiter()
    key = str(uuid4())
    good_calls, bad_calls = simulate_requests(rl, 20, key)
    assert bad_calls == 10
    assert good_calls == 10


def test_rate_limiting_recovers():
    rl = RateLimiter()
    key = str(uuid4())

    with freeze_time("2012-01-14 12:00:01"):
        good_calls, bad_calls = simulate_requests(rl, 20, key)
        assert bad_calls == 10
        assert good_calls == 10

    with freeze_time("2012-01-14 12:00:01"):
        good_calls, bad_calls = simulate_requests(rl, 20, key)
        assert bad_calls == 20
        assert good_calls == 0

    with freeze_time("2012-01-14 12:00:31"):
        good_calls, bad_calls = simulate_requests(rl, 20, key)
        assert bad_calls == 15
        assert good_calls == 5

    with freeze_time("2012-01-14 12:01:31"):
        good_calls, bad_calls = simulate_requests(rl, 20, key)
        assert bad_calls == 10
        assert good_calls == 10
