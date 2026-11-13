"""Sends Temporal logs to the team's logs product as signed internal logs."""

import json
import datetime as dt

from django.conf import settings

import structlog

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.ai_observability.team_capture import TeamNotFound, get_team_api_token

from products.logs.backend.facade.internal_logs import (
    InternalLogEntry,
    InternalLogsProducer,
    InternalLogsProducerConfig,
)

logger = structlog.get_logger(__name__)


async def _api_token(team_id: int) -> str | None:
    try:
        return await database_sync_to_async_pool(get_team_api_token)(team_id)
    except TeamNotFound:
        return None


class InternalLogsSink:
    def __init__(self, producer: InternalLogsProducer) -> None:
        self._producer = producer

    @classmethod
    def from_settings(cls) -> "InternalLogsSink | None":
        producer = InternalLogsProducer(InternalLogsProducerConfig.from_settings(), _api_token)
        return cls(producer) if producer.enabled else None

    def offer(self, message: bytes) -> None:
        """Takes one rendered `log_entries` message. Call it from the event loop the worker runs on."""
        try:
            entry = json.loads(message)
            source = entry["log_source"]
            # An unmapped workflow type has no source, and the producer drops a source it cannot sign.
            if not source:
                return
            self._producer.enqueue(
                source,
                [
                    InternalLogEntry(
                        team_id=int(entry["team_id"]),
                        log_source_id=str(entry["log_source_id"] or ""),
                        instance_id=str(entry["instance_id"] or ""),
                        timestamp=dt.datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S.%f"),
                        level=str(entry["level"]),
                        message=str(entry["message"]),
                    )
                ],
            )
            self._producer.flush()
        except Exception:
            # A logs product failure must never stop the `log_entries` write.
            logger.exception("Failed to send a Temporal log to the logs product")

    async def drain(self) -> None:
        # As long as a record may still retry, like the Kafka flush that runs before this.
        await self._producer.drain(settings.LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS / 1000)
