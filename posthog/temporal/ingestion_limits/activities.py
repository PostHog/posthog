"""Temporal activities for ingestion limits monitoring."""

from datetime import UTC, datetime
from uuid import uuid4

from django.conf import settings

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.ingestion_limits.queries import get_high_volume_distinct_ids_query
from posthog.temporal.ingestion_limits.reporting import (
    format_kafka_messages,
    format_slack_message,
    send_to_kafka,
    send_to_slack,
)
from posthog.temporal.ingestion_limits.types import (
    HighVolumeDistinctId,
    IngestionLimitsReport,
    IngestionLimitsWorkflowInput,
    ReportDestination,
    ReportIngestionLimitsInput,
)

LOGGER = get_logger(__name__)


@activity.defn(name="query-ingestion-limits")
async def query_ingestion_limits_activity(inputs: IngestionLimitsWorkflowInput) -> IngestionLimitsReport:
    """Query ClickHouse for teams that are submitting high rates of events with the same distinct ID.

    Args:
        inputs: Workflow input parameters

    Returns:
        IngestionLimitsReport with list of offending teams and distinct IDs found
        and the number of events counted for each during the time window
    """
    async with Heartbeater():
        bind_contextvars(
            time_window_minutes=inputs.time_window_minutes,
            event_threshold=inputs.event_threshold,
        )
        logger = LOGGER.bind()
        logger.info(
            "Querying ingestion limits from ClickHouse: window={inputs.time_window_minutes} minutes, threshold={inputs.event_threshold}"
        )

        query = get_high_volume_distinct_ids_query(inputs.time_window_minutes)

        high_volume_distinct_ids: list[HighVolumeDistinctId] = []
        total_candidates = 0

        try:
            async with get_client(default_format="JSONEachRow") as client:
                query_id = str(uuid4())
                async for row in client.stream_query_as_jsonl(query, query_id=query_id):
                    offending_event_count = int(row.get("offending_event_count", 0))
                    if offending_event_count >= inputs.event_threshold:
                        high_volume_distinct_ids.append(
                            HighVolumeDistinctId(
                                team_id=int(row.get("team_id", 0)),
                                distinct_id=row["distinct_id"],
                                offending_event_count=offending_event_count,
                            )
                        )
                    total_candidates += 1

        except Exception as e:
            logger.exception("Error querying ClickHouse for ingestion limits", error=str(e))
            raise

        # TODO: validate offending teams in the report aren't already marked via Django event restrictions API

        logger.info(
            "Completed ingestion limits query",
            high_volume_count=len(high_volume_distinct_ids),
            total_candidates=total_candidates,
        )

        return IngestionLimitsReport(
            high_volume_distinct_ids=high_volume_distinct_ids,
            total_candidates=total_candidates,
            timestamp=datetime.now(UTC),
            event_threshold=inputs.event_threshold,
            time_window_minutes=inputs.time_window_minutes,
        )


@activity.defn(name="report-ingestion-limits")
async def report_ingestion_limits_activity(inputs: ReportIngestionLimitsInput) -> IngestionLimitsReport:
    """Report ingestion limits results to Slack and/or Kafka.

    Args:
        inputs: Contains workflow inputs and report data

    Returns:
        The ingestion limits report
    """
    async with Heartbeater():
        bind_contextvars(
            report_destination=inputs.workflow_inputs.report_destination.value,
            high_volume_count=len(inputs.report.high_volume_distinct_ids),
        )
        logger = LOGGER.bind()
        logger.info("Reporting ingestion limits")

        # we can report to slack whether the report contains any teams of interest or not
        should_send_slack = (
            inputs.workflow_inputs.report_destination
            in (
                ReportDestination.SLACK,
                ReportDestination.BOTH,
            )
            and inputs.workflow_inputs.slack_token is not None
        )

        # ingestion warnings should only go out if we have a problem to report
        should_send_kafka = (
            inputs.workflow_inputs.report_destination
            in (
                ReportDestination.KAFKA,
                ReportDestination.BOTH,
            )
            and len(inputs.report.high_volume_distinct_ids) > 0
        )

        if should_send_slack:
            try:
                slack_channel = inputs.workflow_inputs.slack_channel or getattr(
                    settings, "SLACK_INGESTION_EVENT_RESTRICTIONS_CHANNEL", "#alerts-ingestion"
                )
                slack_message = format_slack_message(inputs.report)
                await send_to_slack(channel=slack_channel, message=slack_message)
                logger.info("Sent ingestion limits report to Slack", channel=slack_channel)
            except Exception as e:
                logger.exception(
                    "Failed to send Slack message", error=str(e), channel=inputs.workflow_inputs.slack_channel
                )
                # Don't raise - continue to try Kafka if enabled

        if should_send_kafka:
            try:
                kafka_topic = inputs.workflow_inputs.kafka_topic
                kafka_messages = format_kafka_messages(inputs.report)
                await send_to_kafka(topic=kafka_topic, messages=kafka_messages)
                logger.info(
                    "Sent ingestion limits report to Kafka",
                    topic=kafka_topic,
                    message_count=len(kafka_messages),
                )
            except Exception as e:
                logger.exception("Failed to send Kafka message", error=str(e), topic=kafka_topic)
                # Don't raise - Slack may have succeeded

        logger.info("Completed reporting ingestion limits")
        return inputs.report
