"""Tests for `enqueue_pointer_message` — the activity that sends the
single SQS pointer to billing.

We mock the SQS producer so the test verifies (a) the queue name we route
to, (b) the exact JSON body shape billing will read, and (c) the message
attributes.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from posthog.temporal.usage_report.activities import SQS_POINTER_VERSION, SQS_QUEUE_NAME, enqueue_pointer_message
from posthog.temporal.usage_report.types import AggregateResult, EnqueuePointerInputs, WorkflowContext


def _ctx() -> WorkflowContext:
    return WorkflowContext(
        run_id="run-test",
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str="2026-05-04",
    )


def _agg() -> AggregateResult:
    return AggregateResult(
        chunk_keys=[
            "tasks/billing/usage_reports/2026-05-04/run-test/chunks/chunk_0000.jsonl.gz",
            "tasks/billing/usage_reports/2026-05-04/run-test/chunks/chunk_0001.jsonl.gz",
        ],
        manifest_key="tasks/billing/usage_reports/2026-05-04/run-test/manifest.json",
        total_orgs=12345,
        total_orgs_with_usage=678,
    )


@pytest.mark.asyncio
async def test_pointer_uses_v2_queue_and_correct_payload(activity_environment) -> None:
    """End-to-end activity test: sends to `usage_reports_v2` with the
    expected pointer body and metadata attributes.
    """
    captured: dict[str, Any] = {}
    fake_producer = MagicMock()
    fake_producer.send_message.return_value = {"MessageId": "abc"}

    def fake_get_producer(queue_name):
        captured["queue_name"] = queue_name
        return fake_producer

    with (
        patch("posthog.temporal.usage_report.activities.settings") as mock_settings,
        patch("posthog.temporal.usage_report.activities.bucket", return_value="posthog-billing-usage-reports"),
        patch("ee.sqs.SQSProducer.get_sqs_producer", side_effect=fake_get_producer),
        patch("posthog.temporal.usage_report.activities.get_instance_region", return_value="US"),
    ):
        mock_settings.EE_AVAILABLE = True
        mock_settings.SITE_URL = "https://us.posthog.com"

        await activity_environment.run(
            enqueue_pointer_message,
            EnqueuePointerInputs(ctx=_ctx(), aggregate=_agg()),
        )

    # Routed to the new dedicated queue
    assert captured["queue_name"] == "usage_reports_v2"
    assert SQS_QUEUE_NAME == "usage_reports_v2"

    fake_producer.send_message.assert_called_once()
    call_kwargs = fake_producer.send_message.call_args.kwargs

    # Body has every field billing reads
    body = json.loads(call_kwargs["message_body"])
    assert body == {
        "version": SQS_POINTER_VERSION,
        "run_id": "run-test",
        "date": "2026-05-04",
        "period_start": "2026-05-04T00:00:00+00:00",
        "period_end": "2026-05-04T23:59:59.999999+00:00",
        "region": "US",
        "site_url": "https://us.posthog.com",
        "bucket": "posthog-billing-usage-reports",
        "manifest_key": "tasks/billing/usage_reports/2026-05-04/run-test/manifest.json",
        "chunk_prefix": "tasks/billing/usage_reports/2026-05-04/run-test/chunks/",
        "chunk_count": 2,
        "total_orgs": 12345,
        "total_orgs_with_usage": 678,
    }

    # Metadata attributes carry routing/versioning info billing keys off
    assert call_kwargs["message_attributes"] == {
        "content_type": "application/json",
        "schema_version": str(SQS_POINTER_VERSION),
        "run_id": "run-test",
    }


@pytest.mark.asyncio
async def test_pointer_skipped_when_ee_unavailable(activity_environment) -> None:
    """Self-hosted (no EE) → activity is a no-op, no SQS import or call."""
    fake_producer = MagicMock()

    with (
        patch("posthog.temporal.usage_report.activities.settings") as mock_settings,
        patch("ee.sqs.SQSProducer.get_sqs_producer", return_value=fake_producer) as get_producer,
    ):
        mock_settings.EE_AVAILABLE = False

        await activity_environment.run(
            enqueue_pointer_message,
            EnqueuePointerInputs(ctx=_ctx(), aggregate=_agg()),
        )

    get_producer.assert_not_called()
    fake_producer.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_pointer_raises_when_producer_misconfigured(activity_environment) -> None:
    """If `get_sqs_producer` returns None we should fail loudly (so Temporal
    retries) rather than silently drop the pointer.
    """
    with (
        patch("posthog.temporal.usage_report.activities.settings") as mock_settings,
        patch("posthog.temporal.usage_report.activities.bucket", return_value="posthog"),
        patch("ee.sqs.SQSProducer.get_sqs_producer", return_value=None),
    ):
        mock_settings.EE_AVAILABLE = True
        mock_settings.SITE_URL = "https://us.posthog.com"

        with pytest.raises(Exception, match="usage_reports_v2"):
            await activity_environment.run(
                enqueue_pointer_message,
                EnqueuePointerInputs(ctx=_ctx(), aggregate=_agg()),
            )


@pytest.mark.asyncio
async def test_pointer_raises_when_send_returns_none(activity_environment) -> None:
    """`send_message` returning `None` indicates an SQS error — must raise
    so Temporal retries.
    """
    fake_producer = MagicMock()
    fake_producer.send_message.return_value = None

    with (
        patch("posthog.temporal.usage_report.activities.settings") as mock_settings,
        patch("posthog.temporal.usage_report.activities.bucket", return_value="posthog"),
        patch("ee.sqs.SQSProducer.get_sqs_producer", return_value=fake_producer),
        patch("posthog.temporal.usage_report.activities.get_instance_region", return_value="US"),
    ):
        mock_settings.EE_AVAILABLE = True
        mock_settings.SITE_URL = "https://us.posthog.com"

        with pytest.raises(Exception, match="no response"):
            await activity_environment.run(
                enqueue_pointer_message,
                EnqueuePointerInputs(ctx=_ctx(), aggregate=_agg()),
            )


def test_v2_queue_is_configured_in_settings() -> None:
    queues = getattr(settings, "SQS_QUEUES", {})
    assert SQS_QUEUE_NAME in queues, (
        f"Queue {SQS_QUEUE_NAME!r} must be declared in settings.SQS_QUEUES — "
        f"otherwise the pointer activity raises after S3 work is done"
    )
