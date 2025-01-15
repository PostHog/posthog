import os
import django

from dagster import (
    Config,
    MaterializeResult,
    asset,
)

# setup PostHog Django Project

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.clickhouse.client import sync_execute  # noqa


class ClickHouseConfig(Config):
    result_path: str = "/tmp/clickhouse_version.txt"


@asset
def get_clickhouse_version(config: ClickHouseConfig) -> MaterializeResult:
    version = sync_execute("SELECT version()")[0][0]
    with open(config.result_path, "w") as f:
        f.write(version)
    return MaterializeResult(metadata={"version": version})


@asset(deps=[get_clickhouse_version])
def print_clickhouse_version(config: ClickHouseConfig):
    with open(config.result_path) as f:
        print(f.read())  # noqa
    return MaterializeResult(metadata={"version": config.result_path})
