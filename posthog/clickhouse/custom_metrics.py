from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import dataclass

from posthog.clickhouse.cluster import ClickhouseCluster, Query


@dataclass
class MetricsClient:
    cluster: ClickhouseCluster

    def increment(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> Future[None]:
        if labels is None:
            labels = {}

        if value < 0:
            raise ValueError("value must be non-negative")

        return self.cluster.any_host(
            Query(
                "INSERT INTO custom_metrics_counter_events (name, labels, increment) VALUES",
                [(name, labels, value)],
            )
        )
