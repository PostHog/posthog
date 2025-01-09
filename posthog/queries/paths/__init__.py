from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.queries.paths import ClickhousePaths as Paths
else:
    from posthog.queries.paths.paths import Paths  # type: ignore
