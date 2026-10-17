from dataclasses import asdict

import pytest
from unittest.mock import patch

from posthog.tasks.usage_ingestion import enqueue_usage_records, send_usage_records
from posthog.usage_ingestion.client import UsageRecord

RECORD = UsageRecord(
    record_id="request-1",
    producer_id="test-producer",
    team_id=2,
    usage_key="test-usage",
    unit="requests",
    quantity=1,
    timestamp_ms=1000,
)


@pytest.mark.parametrize(
    "address,teams,queued",
    [("localhost:1", "*", True), ("localhost:1", "2", True), ("localhost:1", "3", False), ("", "*", False)],
)
def test_enqueue_respects_reporting_configuration(
    monkeypatch: pytest.MonkeyPatch, address: str, teams: str, queued: bool
) -> None:
    monkeypatch.setenv("USAGE_INGESTION_ADDR", address)
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", teams)
    with patch.object(send_usage_records, "delay") as publish:
        enqueue_usage_records([RECORD], site="test")
    if queued:
        publish.assert_called_once_with([asdict(RECORD)], "test")
    else:
        publish.assert_not_called()


def test_enqueue_failure_does_not_fail_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_ADDR", "localhost:1")
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "*")
    with patch.object(send_usage_records, "delay", side_effect=RuntimeError("broker unavailable")):
        enqueue_usage_records([RECORD], site="test")


def test_worker_delivery_preserves_record_identity_and_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_ADDR", "localhost:1")
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "*")
    with patch("posthog.usage_ingestion.client.grpc.insecure_channel") as channel:
        with patch("posthog.usage_ingestion.client.service_pb2_grpc.UsageIngestionStub") as stub:
            stub.return_value.IngestBillingUsage.return_value.accepted_record_ids = [RECORD.record_id]
            send_usage_records.run([asdict(RECORD)], "test")
    channel.assert_called_once_with("localhost:1")
    record = stub.return_value.IngestBillingUsage.call_args.args[0].records[0]
    assert record.record_id == RECORD.record_id
    assert record.timestamp_ms == RECORD.timestamp_ms
    assert record.team_id == RECORD.team_id
    assert record.quantity == RECORD.quantity
