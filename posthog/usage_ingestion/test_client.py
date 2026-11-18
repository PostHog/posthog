from dataclasses import replace

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

import grpc

from posthog.usage_ingestion import client
from posthog.usage_ingestion.client import UsageRecord, _timeout_seconds, areport_usage, report_usage, team_is_enabled
from posthog.usage_ingestion.generated.usage_ingestion.v1 import service_pb2

ERRORS = [grpc.RpcError(), RuntimeError("boom")]
REPORTING_ENV = {"USAGE_INGESTION_ADDR": "localhost:1", "USAGE_INGESTION_REPORT_TEAMS": "*"}
RECORD = UsageRecord(record_id="r", producer_id="p", team_id=2, usage_key="k", unit="rows", quantity=1)


def _rpc_error(status_code: grpc.StatusCode) -> grpc.RpcError:
    error = grpc.RpcError()
    error.code = lambda: status_code
    return error


def _channel() -> MagicMock:
    channel = MagicMock()
    channel.__enter__.return_value = channel
    return channel


def _async_channel() -> MagicMock:
    channel = MagicMock()
    channel.__aenter__.return_value = channel
    return channel


def test_team_is_enabled_uses_the_shared_team_list(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "2, 4")

    assert team_is_enabled(2)
    assert team_is_enabled(4)
    assert not team_is_enabled(3)


def test_team_is_enabled_supports_all_teams(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "*")

    assert team_is_enabled(123)


def test_timeout_converts_milliseconds_to_the_seconds_grpc_expects(monkeypatch) -> None:
    monkeypatch.delenv("USAGE_INGESTION_TIMEOUT_MS", raising=False)
    assert _timeout_seconds() == 5.0

    monkeypatch.setenv("USAGE_INGESTION_TIMEOUT_MS", "250")
    assert _timeout_seconds() == 0.25


@pytest.mark.parametrize(
    ("accepted_ids", "sent", "failed"),
    [
        (["r", "r-2"], ["k", "k-2"], []),
        (["r"], ["k"], ["k-2"]),
    ],
    ids=["accepted", "partially_rejected"],
)
def test_reporting_counts_only_records_accepted_by_the_service(
    monkeypatch, accepted_ids: list[str], sent: list[str], failed: list[str]
) -> None:
    records = [RECORD, replace(RECORD, record_id="r-2", usage_key="k-2")]
    channel = _channel()
    stub = MagicMock()
    stub.IngestBillingUsage.return_value = service_pb2.IngestBillingUsageResponse(accepted_record_ids=accepted_ids)
    sent_counter = MagicMock()
    failed_counter = MagicMock()
    monkeypatch.setattr(client, "USAGE_INGESTION_RECORDS_SENT_TOTAL", sent_counter)
    monkeypatch.setattr(client, "USAGE_INGESTION_RECORDS_FAILED_TOTAL", failed_counter)

    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", return_value=channel):
            with patch("posthog.usage_ingestion.client.service_pb2_grpc.UsageIngestionStub", return_value=stub):
                report_usage(records, site="test")

    assert sent_counter.labels.call_args_list == [call(producer_id="p", usage_key=usage_key) for usage_key in sent]
    assert failed_counter.labels.call_args_list == [
        call(producer_id="p", usage_key=usage_key, error_code="rejected") for usage_key in failed
    ]


def test_reporting_names_the_producer_in_grpc_metadata() -> None:
    channel = _channel()
    stub = MagicMock()
    stub.IngestBillingUsage.return_value = service_pb2.IngestBillingUsageResponse(accepted_record_ids=["r"])

    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", return_value=channel):
            with patch("posthog.usage_ingestion.client.service_pb2_grpc.UsageIngestionStub", return_value=stub):
                report_usage([RECORD], site="test")

    assert stub.IngestBillingUsage.call_args.kwargs["metadata"] == (("x-client-name", "p"),)


def test_reporting_counts_terminal_grpc_failures(monkeypatch) -> None:
    channel = _channel()
    stub = MagicMock()
    stub.IngestBillingUsage.side_effect = _rpc_error(grpc.StatusCode.INVALID_ARGUMENT)
    failed_counter = MagicMock()
    monkeypatch.setattr(client, "USAGE_INGESTION_RECORDS_FAILED_TOTAL", failed_counter)

    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", return_value=channel):
            with patch("posthog.usage_ingestion.client.service_pb2_grpc.UsageIngestionStub", return_value=stub):
                report_usage([RECORD], site="test")

    assert failed_counter.labels.call_args_list == [call(producer_id="p", usage_key="k", error_code="InvalidArgument")]


def test_reporting_retries_transient_grpc_failures(monkeypatch) -> None:
    channel = _channel()
    stub = MagicMock()
    stub.IngestBillingUsage.side_effect = [
        _rpc_error(grpc.StatusCode.UNAVAILABLE),
        service_pb2.IngestBillingUsageResponse(accepted_record_ids=["r"]),
    ]
    retries_counter = MagicMock()
    sent_counter = MagicMock()
    monkeypatch.setattr(client, "USAGE_INGESTION_RETRIES_TOTAL", retries_counter)
    monkeypatch.setattr(client, "USAGE_INGESTION_RECORDS_SENT_TOTAL", sent_counter)

    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", return_value=channel):
            with patch("posthog.usage_ingestion.client.service_pb2_grpc.UsageIngestionStub", return_value=stub):
                with patch("posthog.usage_ingestion.client.sleep") as sleep:
                    report_usage([RECORD], site="test")

    assert stub.IngestBillingUsage.call_count == 2
    assert retries_counter.labels.call_args_list == [call(producer_id="p", error_code="Unavailable")]
    sleep.assert_called_once_with(0.1)
    sent_counter.labels.assert_called_once_with(producer_id="p", usage_key="k")


def test_reporting_drops_records_after_exhausting_transient_retries(monkeypatch) -> None:
    channel = _channel()
    stub = MagicMock()
    stub.IngestBillingUsage.side_effect = [_rpc_error(grpc.StatusCode.UNAVAILABLE) for _ in range(3)]
    retries_counter = MagicMock()
    failed_counter = MagicMock()
    monkeypatch.setattr(client, "USAGE_INGESTION_RETRIES_TOTAL", retries_counter)
    monkeypatch.setattr(client, "USAGE_INGESTION_RECORDS_FAILED_TOTAL", failed_counter)

    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", return_value=channel):
            with patch("posthog.usage_ingestion.client.service_pb2_grpc.UsageIngestionStub", return_value=stub):
                with patch("posthog.usage_ingestion.client.sleep") as sleep:
                    report_usage([RECORD], site="test")

    assert stub.IngestBillingUsage.call_count == 3
    assert retries_counter.labels.call_args_list == [
        call(producer_id="p", error_code="Unavailable"),
        call(producer_id="p", error_code="Unavailable"),
    ]
    assert failed_counter.labels.call_args_list == [call(producer_id="p", usage_key="k", error_code="Unavailable")]
    assert sleep.call_args_list == [call(0.1), call(0.2)]


async def test_async_reporting_retries_transient_grpc_failures(monkeypatch) -> None:
    channel = _async_channel()
    stub = MagicMock()
    stub.IngestBillingUsage = AsyncMock(
        side_effect=[
            _rpc_error(grpc.StatusCode.UNAVAILABLE),
            service_pb2.IngestBillingUsageResponse(accepted_record_ids=["r"]),
        ]
    )
    retries_counter = MagicMock()
    sent_counter = MagicMock()
    monkeypatch.setattr(client, "USAGE_INGESTION_RETRIES_TOTAL", retries_counter)
    monkeypatch.setattr(client, "USAGE_INGESTION_RECORDS_SENT_TOTAL", sent_counter)

    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.aio.insecure_channel", return_value=channel):
            with patch("posthog.usage_ingestion.client.service_pb2_grpc.UsageIngestionStub", return_value=stub):
                with patch("posthog.usage_ingestion.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
                    await areport_usage([RECORD], site="test")

    assert stub.IngestBillingUsage.call_count == 2
    assert retries_counter.labels.call_args_list == [call(producer_id="p", error_code="Unavailable")]
    sleep.assert_awaited_once_with(0.1)
    sent_counter.labels.assert_called_once_with(producer_id="p", usage_key="k")


# Every producer calls these after committing work of its own, so a raise here fails an activity
# that is already done, and the retry re-runs everything that ran before it.
@pytest.mark.parametrize("error", ERRORS)
def test_reporting_never_raises_into_the_producer(error: Exception) -> None:
    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", side_effect=error):
            report_usage([RECORD], site="test")


@pytest.mark.parametrize("error", ERRORS)
async def test_async_reporting_never_raises_into_the_producer(error: Exception) -> None:
    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.aio.insecure_channel", side_effect=error):
            await areport_usage([RECORD], site="test")
