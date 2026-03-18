import dagster

from posthog.clickhouse.client import sync_execute  # noqa


class ClickHouseConfig(dagster.Config):
    result_path: str = "/tmp/clickhouse_version.txt"


@dagster.asset
def get_clickhouse_version(config: ClickHouseConfig) -> dagster.MaterializeResult:
    version = sync_execute("SELECT version()")[0][0]
    with open(config.result_path, "w") as f:
        f.write(version)

    return dagster.MaterializeResult(metadata={"version": version})


@dagster.asset(deps=[get_clickhouse_version])
def print_clickhouse_version(config: ClickHouseConfig):
    with open(config.result_path) as f:
        print(f.read())  # noqa

    return dagster.MaterializeResult(metadata={"version": config.result_path})
