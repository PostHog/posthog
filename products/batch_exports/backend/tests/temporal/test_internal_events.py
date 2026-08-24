import datetime as dt

import pytest
import unittest.mock

from products.batch_exports.backend.models.batch_export import BatchExportRun
from products.batch_exports.backend.temporal.batch_exports import (
    make_internal_events_payload,
    try_cancel_running_backfills,
    try_pause_batch_export,
    try_produce,
)

TEAM_ID = 1
BATCH_EXPORT_ID = "d0ec7b0c-6b3d-4a76-8ea4-6a5b2c0e1f5a"
RUN_ID = "b3f5a9d1-2c4e-4f6a-8b7c-9d0e1f2a3b4c"
BATCH_EXPORT_NAME = "test export"
DESTINATION_TYPE = "S3"
INTERVAL_START = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
INTERVAL_END = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

BASE_PROPERTIES = {
    "batch_export_id": BATCH_EXPORT_ID,
    "batch_export_run_id": RUN_ID,
    "batch_export_name": BATCH_EXPORT_NAME,
    "data_interval_start": INTERVAL_START.isoformat(),
    "data_interval_end": INTERVAL_END.isoformat(),
    "destination_type": DESTINATION_TYPE,
}


def make_payloads(status: BatchExportRun.Status, error: str | None = "Oh No!", was_paused: bool = False):
    return make_internal_events_payload(
        status,
        TEAM_ID,
        BATCH_EXPORT_ID,
        RUN_ID,
        BATCH_EXPORT_NAME,
        INTERVAL_START,
        INTERVAL_END,
        DESTINATION_TYPE,
        10,
        error,
        was_paused,
    )


@pytest.mark.parametrize(
    "status,expected_event,expected_extra_properties",
    [
        (BatchExportRun.Status.COMPLETED, "$batch_export_run_completed", {"rows_exported": 10}),
        (BatchExportRun.Status.CANCELLED, "$batch_export_run_cancelled", {}),
        (BatchExportRun.Status.FAILED_BILLING, "$batch_export_run_failed_billing", {"error": "Oh No!"}),
        (BatchExportRun.Status.FAILED, "$batch_export_run_failed", {"error": "Oh No!"}),
    ],
)
def test_make_internal_events_payload_matches_status(status, expected_event, expected_extra_properties):
    """Test 'make_internal_events_payload' generates the event matching each status."""
    payloads = make_payloads(status)

    assert len(payloads) == 1

    payload = payloads[0]
    assert payload["team_id"] == TEAM_ID
    assert payload["event"]["event"] == expected_event
    assert payload["event"]["distinct_id"] == f"team_{TEAM_ID}"
    assert payload["event"]["properties"] == {**BASE_PROPERTIES, **expected_extra_properties}


def test_make_internal_events_payload_truncates_error():
    """Test 'make_internal_events_payload' truncates long error messages for failed runs."""
    payloads = make_payloads(BatchExportRun.Status.FAILED, error="e" * 2000)

    assert payloads[0]["event"]["properties"]["error"] == "e" * 1000


def test_make_internal_events_payload_includes_paused_event_only_when_paused():
    """Test the '$batch_export_paused' event is generated if and only if the batch export was paused."""
    paused_payloads = make_payloads(BatchExportRun.Status.FAILED, was_paused=True)

    assert [payload["event"]["event"] for payload in paused_payloads] == [
        "$batch_export_run_failed",
        "$batch_export_paused",
    ]
    assert paused_payloads[1]["event"]["properties"] == {**BASE_PROPERTIES, "error": "Oh No!"}
    assert paused_payloads[1]["event"]["distinct_id"] == f"team_{TEAM_ID}"

    not_paused_payloads = make_payloads(BatchExportRun.Status.FAILED, was_paused=False)

    assert [payload["event"]["event"] for payload in not_paused_payloads] == ["$batch_export_run_failed"]


@pytest.mark.asyncio
async def test_try_pause_batch_export_returns_false_when_pausing_raises():
    """Test 'try_pause_batch_export' swallows exceptions and reports no pause happened."""
    with unittest.mock.patch(
        "products.batch_exports.backend.temporal.batch_exports.pause_batch_export_over_failure_threshold",
        side_effect=RuntimeError("Oh No!"),
    ):
        assert await try_pause_batch_export(BATCH_EXPORT_ID) is False


@pytest.mark.asyncio
async def test_try_cancel_running_backfills_returns_none_when_cancelling_raises():
    """Test 'try_cancel_running_backfills' swallows exceptions and reports no cancellations."""
    with unittest.mock.patch(
        "products.batch_exports.backend.temporal.batch_exports.cancel_running_backfills",
        side_effect=RuntimeError("Oh No!"),
    ):
        assert await try_cancel_running_backfills(BATCH_EXPORT_ID) is None


@pytest.mark.asyncio
async def test_try_produce_swallows_producer_errors():
    """Test 'try_produce' does not raise when the underlying producer fails."""
    with unittest.mock.patch(
        "products.batch_exports.backend.temporal.batch_exports.async_producer_scope",
        side_effect=RuntimeError("Oh No!"),
    ):
        await try_produce([{"key": "value"}], topic="some_topic")
