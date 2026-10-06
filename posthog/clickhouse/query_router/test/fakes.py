from posthog.clickhouse.query_router.config import Pool, QueryClass, RouterMode, RouterSettings


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def router_settings(*, mode: RouterMode = RouterMode.ENFORCE, limit: int) -> RouterSettings:
    # Every pool and class is listed, so an enforce mode applies to whatever a test admits.
    return RouterSettings(
        mode=mode,
        enforced=frozenset((pool, query_class) for pool in Pool for query_class in QueryClass),
        limits=dict.fromkeys(Pool, limit),
    )
