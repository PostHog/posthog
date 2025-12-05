import dagster
import psycopg2
import psycopg2.extras
from clickhouse_driver.errors import Error, ErrorCodes

from posthog.clickhouse.cluster import ClickhouseCluster, ExponentialBackoff, RetryPolicy, get_cluster
from posthog.redis import get_client, redis


class ClickhouseClusterResource(dagster.ConfigurableResource):
    """
    The ClickHouse cluster used to run the job.
    """

    client_settings: dict[str, str] = {
        "lightweight_deletes_sync": "0",
        "max_execution_time": "0",
        "max_memory_usage": "0",
        "mutations_sync": "0",
        "receive_timeout": f"{15 * 60}",  # some synchronous queries like dictionary checksumming can be very slow to return
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
                    and (
                        (
                            e.code
                            in (  # these are typically transient errors and unrelated to the query being executed
                                ErrorCodes.NETWORK_ERROR,
                                ErrorCodes.TOO_MANY_SIMULTANEOUS_QUERIES,
                                ErrorCodes.NOT_ENOUGH_SPACE,
                                ErrorCodes.SOCKET_TIMEOUT,
                                439,  # CANNOT_SCHEDULE_TASK: "Cannot schedule a task: cannot allocate thread"
                            )
                        )
                        # queries that exceed memory limits can be retried if they were killed due to total server
                        # memory consumption, but we should avoid retrying queries that were killed due to query limits
                        or (e.code == ErrorCodes.MEMORY_LIMIT_EXCEEDED and "Memory limit (total) exceeded" in e.message)
                    )
                ),
            ),
        )


class RedisResource(dagster.ConfigurableResource):
    """
    A Redis resource that can be used to store and retrieve data.
    """

    def create_resource(self, context: dagster.InitResourceContext) -> redis.Redis:
        client = get_client()
        return client


class PostgresResource(dagster.ConfigurableResource):
    """
    A Postgres database connection resource that returns a psycopg2 connection.
    """

    host: str
    port: str = "5432"
    database: str
    user: str
    password: str

    def create_resource(self, context: dagster.InitResourceContext) -> psycopg2.extensions.connection:
        return psycopg2.connect(
            host=self.host,
            port=int(self.port),
            database=self.database,
            user=self.user,
            password=self.password,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
