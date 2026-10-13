from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import dataclass

from clickhouse_driver import Client
from clickhouse_driver.errors import ErrorCodes, ServerException

from posthog.clickhouse.cluster import ClickhouseCluster, Query


@dataclass(frozen=False)
class MetricsClient:
    cluster: ClickhouseCluster

    def increment(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> Future[None]:
        if labels is None:
            labels = {}

        if value < 0:
            raise ValueError("value must be non-negative")

        insert = Query(
            "INSERT INTO custom_metrics_counter_events (name, labels, increment) VALUES",
            [(name, labels, value)],
        )

        def run(client: Client) -> None:
            try:
                insert(client)
            except ServerException as e:
                # Only PostHog Cloud has the counter table (posthog-cloud-infra declares it); elsewhere the
                # metric is dropped.
                if e.code != ErrorCodes.UNKNOWN_TABLE:
                    raise

        return self.cluster.any_host(run)
