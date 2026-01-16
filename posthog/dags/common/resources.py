import asyncio
from collections.abc import Generator
from urllib.parse import urlparse

import dagster
import psycopg2
import psycopg2.extras
import posthoganalytics
from clickhouse_driver.errors import Error, ErrorCodes

from posthog.clickhouse.cluster import ClickhouseCluster, ExponentialBackoff, RetryPolicy, get_cluster
from posthog.kafka_client.client import _KafkaProducer
from posthog.redis import get_client, redis
from posthog.utils import initialize_self_capture_api_token


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


class PostHogAnalyticsResource(dagster.ConfigurableResource):
    personal_api_key: str | None

    def create_resource(self, context: dagster.InitResourceContext):
        assert context.log is not None

        context.log.info("Initializing PostHogAnalyticsResource")

        if not (self.personal_api_key or "").strip() and not (posthoganalytics.personal_api_key or "").strip():
            context.log.warning(
                "Personal API key not set on the PostHogAnalyticsResource. Local feature flag evaluation will not work."
            )

        asyncio.run(initialize_self_capture_api_token())
        posthoganalytics.personal_api_key = self.personal_api_key

        return None


class PostgresURLResource(dagster.ConfigurableResource):
    """
    Postgres connection that parses a connection URL.
    Delegates to PostgresResource for actual connection logic.
    Expects format: postgres://user:pass@host:port/dbname
    """

    connection_url: str

    def create_resource(self, context: dagster.InitResourceContext) -> psycopg2.extensions.connection:
        parsed = urlparse(self.connection_url)
        pg = PostgresResource(
            host=parsed.hostname or "",
            port=str(parsed.port or 5432),
            database=parsed.path.lstrip("/"),
            user=parsed.username or "",
            password=parsed.password or "",
        )
        return pg.create_resource(context)


@dagster.resource
def kafka_producer_resource(context: dagster.InitResourceContext) -> Generator[_KafkaProducer, None, None]:
    """
    Kafka producer resource with proper cleanup.
    Flushes pending messages on teardown.
    """
    producer = _KafkaProducer()
    try:
        yield producer
    finally:
        producer.flush()
