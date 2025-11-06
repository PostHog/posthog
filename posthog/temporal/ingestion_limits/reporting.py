"""Slack and Kafka reporting utilities for ingestion limits."""

import json

from django.conf import settings

import aiohttp
from slack_sdk.web.async_client import AsyncWebClient

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_INGESTION_WARNINGS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.temporal.common.logger import get_logger
from posthog.temporal.ingestion_limits.types import IngestionLimitsReport

LOGGER = get_logger(__name__)


def format_slack_message(report: IngestionLimitsReport) -> dict:
    """Format ingestion limits report as Slack message blocks.

    Args:
        report: The ingestion limits report to format

    Returns:
        Dictionary with 'blocks' and 'text' keys for Slack API
    """
    if not report.high_volume_distinct_ids:
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "✅ *Ingestion Limits Report*\n\nNo high-volume distinct IDs found.",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Time window: {report.time_window_minutes} minutes | Threshold: {report.event_threshold} dup distinct IDs per team",
                    }
                ],
            },
        ]
        text = "Ingestion Limits Report - No issues found"
    else:
        # Format top offenders
        offenders_text = "\n".join(
            [
                f"• Team {item.team_id}: `{item.distinct_id}` ({item.offending_event_count:,} events)"
                for item in report.high_volume_distinct_ids[:20]  # Limit to top 20 for readability
            ]
        )

        if len(report.high_volume_distinct_ids) > 20:
            offenders_text += f"\n... and {len(report.high_volume_distinct_ids) - 20} more"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚠️ *Ingestion Limits Report*\n\nFound {len(report.high_volume_distinct_ids)} high-volume distinct IDs:\n\n{offenders_text}",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Time window: {report.time_window_minutes} minutes | Total candidates: {report.total_candidates}",
                    }
                ],
            },
        ]
        text = f"Ingestion Limits Report - {len(report.high_volume_distinct_ids)} high-volume distinct IDs found"

    return {"blocks": blocks, "text": text}


def format_kafka_messages(report: IngestionLimitsReport) -> list[dict]:
    """Format ingestion limits report as ingestion warning messages for Kafka.

    Each high-volume distinct ID becomes a separate ingestion warning message,
    matching the format used by plugin-server's captureIngestionWarning.

    Args:
        report: The ingestion limits report to format

    Returns:
        List of message dictionaries, each matching the ingestion_warnings table schema:
        - team_id: int
        - source: str (e.g., 'temporal-ingestion-limits')
        - type: str (e.g., 'high_volume_distinct_id')
        - details: str (JSON-stringified dict)
        - timestamp: str (ClickHouse format)
    """
    if not report.high_volume_distinct_ids:
        return []

    timestamp_str = format_clickhouse_timestamp(report.timestamp)
    messages = []

    for item in report.high_volume_distinct_ids:
        details = {
            "distinct_id": item.distinct_id,
            "event_count": item.offending_event_count,
            "time_window_minutes": report.time_window_minutes,
            "events_per_window_threshold": report.event_threshold,
            "suggestion": (
                "Please replace this distinct ID in all event submissions with a session-scoped UUID "
                "(pre-identify) or stable user ID like an email address (post-identify.) "
                "If you need to group events by a wider scope than a single user, add a new event.property "
                "or use PostHog Groups, not distinct ID, to achieve this."
            ),
        }
        messages.append(
            {
                "team_id": item.team_id,
                "source": "ingestion_event_restrictions",
                "type": "high_cardinality_distinct_id",
                "details": json.dumps(details),  # Double-stringify to match plugin-server format
                "timestamp": timestamp_str,
            }
        )

    return messages


async def send_to_slack(channel: str, message: dict, slack_token: str | None = None) -> None:
    """Send Slack message asynchronously.

    Args:
        channel: Slack channel ID or name (e.g., '#alerts' or 'C1234567890')
        message: Message dict with 'blocks' and 'text' keys
        slack_token: Optional Slack bot token (defaults to settings.SLACK_TOKEN)

    Raises:
        ValueError: If slack_token is not provided and not in settings
    """
    token = slack_token or getattr(settings, "SLACK_TOKEN", None)
    if not token:
        raise ValueError("Slack token not provided and SLACK_TOKEN not found in settings")

    async with aiohttp.ClientSession() as session:
        client = AsyncWebClient(token=token, session=session)
        await client.chat_postMessage(channel=channel, **message)


def send_to_kafka(topic: str | None, messages: list[dict]) -> None:
    """Send ingestion warning messages to Kafka topic.

    Args:
        topic: Kafka topic name (defaults to KAFKA_INGESTION_WARNINGS)
        messages: List of message dictionaries to send
    """

    logger = LOGGER.bind(topic=topic, message_count=len(messages))

    if not messages:
        logger.warning("No messages to send to Kafka")
        return

    kafka_topic = topic or KAFKA_INGESTION_WARNINGS
    producer = KafkaProducer()

    # Send each message individually to match plugin-server behavior
    # KafkaProducer.produce() expects a dict and will serialize it with json_serializer
    for message in messages:
        try:
            logger.info("Submitting ingestion warning to Kafka", message=message)
            producer.produce(topic=kafka_topic, data=message)
        except Exception as e:
            logger.exception(f"Failed to submit ingestion warning to Kafka", error=str(e), message=message)
