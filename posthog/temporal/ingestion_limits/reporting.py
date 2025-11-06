"""Slack and Kafka reporting utilities for ingestion limits."""

import json
from typing import Optional

from django.conf import settings

import aiohttp
from slack_sdk.web.async_client import AsyncWebClient

from posthog.kafka_client.client import KafkaProducer
from posthog.temporal.ingestion_limits.types import IngestionLimitsReport


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


def format_kafka_message(report: IngestionLimitsReport) -> dict:
    """Format ingestion limits report as JSON for Kafka.

    Args:
        report: The ingestion limits report to format

    Returns:
        Dictionary ready for JSON serialization
    """
    return {
        "report_type": "ingestion_limits",
        "timestamp": report.timestamp.isoformat(),
        "time_window_minutes": report.time_window_minutes,
        "total_candidates": report.total_candidates,
        "high_volume_distinct_ids": [
            {
                "team_id": item.team_id,
                "distinct_id": item.distinct_id,
                "offending_event_count": item.offending_event_count,
            }
            for item in report.high_volume_distinct_ids
        ],
    }


async def send_to_slack(channel: str, message: dict, slack_token: Optional[str] = None) -> None:
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


def send_to_kafka(topic: str, message: dict) -> None:
    """Send message to Kafka topic.

    Args:
        topic: Kafka topic name
        message: Message dict to serialize as JSON
    """
    producer = KafkaProducer()
    producer.produce(topic=topic, data=json.dumps(message).encode("utf-8"))
