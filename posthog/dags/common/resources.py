import json
import asyncio
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import dagster
import psycopg2
import requests
import tenacity
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


def _is_retryable_http_error(exception: BaseException) -> bool:
    """Check if an HTTP error should be retried."""
    if isinstance(exception, requests.exceptions.HTTPError):
        response = exception.response
        if response is not None and response.status_code in {429, 500, 502, 503, 504}:
            return True
    return isinstance(exception, requests.exceptions.ConnectionError)


@dataclass
class ClayBatchResult:
    """Result from create_batches containing batches and stats for monitoring."""

    batches: list[list[dict]]
    truncated_count: int
    skipped_count: int


class ClayWebhookResource(dagster.ConfigurableResource):
    """Clay webhook client for sending enriched contact data."""

    webhook_url: str
    api_key: str
    timeout: int = 60
    max_batch_bytes: int = 90_000  # 90KB, leaving margin under Clay's 100KB limit
    max_records_per_batch: int = 10  # Rate limit friendly (Clay allows 10 records/sec sustained)
    max_retries: int = 3
    # Fields to truncate in order of priority (least important first).
    # These are array fields where partial data is acceptable.
    # Order: diagnostic/metadata fields -> identifiers -> user-facing data
    truncatable_fields: list[str] = [
        "bounce_reasons",  # Diagnostic info, less critical
        "subjects",  # Email subjects, can be sampled
        "removal_timestamps",  # Timestamps for removals
        "removal_types",  # Types of removal
        "source_type",  # Source identifiers
        "organization_names",  # Org names, can be partial
        "organization_ids",  # Org IDs, can be partial
        "emails",  # Core data, truncated last
    ]

    def _truncate_record_to_fit(self, record: dict) -> dict:
        """Truncate array fields in a record to fit within max_batch_bytes."""
        record = record.copy()
        record_size = self._get_batch_size([record])

        if record_size <= self.max_batch_bytes:
            return record

        # Progressively truncate fields until it fits
        for field in self.truncatable_fields:
            if field not in record or not isinstance(record[field], list):
                continue

            arr = record[field]
            if not arr:
                continue

            # Progressively halve array length until it fits
            while len(arr) > 0 and record_size > self.max_batch_bytes:
                # Halve the array length each iteration
                new_len = max(1, len(arr) // 2)
                if new_len == len(arr):
                    new_len = 0
                record[field] = arr[:new_len]
                record_size = self._get_batch_size([record])
                arr = record[field]

            if record_size <= self.max_batch_bytes:
                break

        return record

    def _post(self, session: requests.Session, data: list[dict]) -> requests.Response:
        """Make a POST request to the webhook."""
        headers = {
            "x-clay-webhook-auth": self.api_key,
            "Content-Type": "application/json",
        }
        response = session.post(
            self.webhook_url,
            json=data,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def _send_with_retry(self, session: requests.Session, data: list[dict]) -> requests.Response:
        """Send data with tenacity retry logic."""
        retryer = tenacity.Retrying(
            stop=tenacity.stop_after_attempt(self.max_retries + 1),
            wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
            retry=tenacity.retry_if_exception(_is_retryable_http_error),
            reraise=True,
        )
        return retryer(self._post, session, data)

    def send(self, data: list[dict]) -> requests.Response:
        """Send data to Clay webhook."""
        with requests.Session() as session:
            return self._send_with_retry(session, data)

    def _get_batch_size(self, batch: list[dict]) -> int:
        """Get the serialized size of a batch in bytes."""
        return len(json.dumps(batch, default=str).encode("utf-8"))

    def create_batches(self, data: list[dict], logger: Any | None = None) -> ClayBatchResult:
        """Split data into batches respecting both record count and byte limits.

        Returns a ClayBatchResult containing:
        - batches: list of batches, each containing records that fit within
          max_records_per_batch and max_batch_bytes constraints
        - truncated_count: number of records that were truncated to fit
        - skipped_count: number of records that were skipped entirely
        """
        if not data:
            return ClayBatchResult(batches=[], truncated_count=0, skipped_count=0)

        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        truncated_count = 0
        skipped_count = 0

        for record in data:
            record_size = self._get_batch_size([record])
            if record_size > self.max_batch_bytes:
                original_size = record_size
                record = self._truncate_record_to_fit(record)
                record_size = self._get_batch_size([record])
                truncated_count += 1
                if logger:
                    logger.info(
                        "Truncated record for domain %s: %d -> %d bytes",
                        record.get("domain", "unknown"),
                        original_size,
                        record_size,
                    )
                if record_size > self.max_batch_bytes:
                    skipped_count += 1
                    if logger:
                        logger.warning(
                            "Skipped oversized record for domain %s: %d bytes exceeds max %d bytes",
                            record.get("domain", "unknown"),
                            record_size,
                            self.max_batch_bytes,
                        )
                    continue

            # Check if adding this record would exceed limits
            candidate = [*current_batch, record]
            if len(candidate) > self.max_records_per_batch or self._get_batch_size(candidate) > self.max_batch_bytes:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [record]
            else:
                current_batch = candidate

        if current_batch:
            batches.append(current_batch)

        if logger:
            if truncated_count > 0:
                logger.info("Truncated %d records to fit batch size limits", truncated_count)
            if skipped_count > 0:
                logger.warning("Skipped %d records that exceeded max batch size", skipped_count)

        return ClayBatchResult(batches=batches, truncated_count=truncated_count, skipped_count=skipped_count)
