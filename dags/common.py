import dagster
from clickhouse_driver.errors import Error, ErrorCodes

from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    ExponentialBackoff,
    RetryPolicy,
    get_cluster,
)


class ClickhouseClusterResource(dagster.ConfigurableResource):
    """
    The ClickHouse cluster used to run the job.
    """

    client_settings: dict[str, str] = {
        "lightweight_deletes_sync": "0",
        "max_execution_time": "0",
        "max_memory_usage": "0",
        "mutations_sync": "0",
        "receive_timeout": f"{10 * 60}",  # some synchronous queries like dictionary checksumming can be very slow to return
    }

    def create_resource(self, context: dagster.InitResourceContext) -> ClickhouseCluster:
        return get_cluster(
            context.log,
            client_settings=self.client_settings,
            retry_policy=RetryPolicy(
                max_attempts=8,
                delay=ExponentialBackoff(20),
                exceptions=lambda e: (
                    isinstance(e, Error)
                    and e.code
                    in (ErrorCodes.NETWORK_ERROR, ErrorCodes.TOO_MANY_SIMULTANEOUS_QUERIES, ErrorCodes.NOT_ENOUGH_SPACE)
                ),
            ),
        )
