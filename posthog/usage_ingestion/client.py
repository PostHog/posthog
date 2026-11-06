import os
import asyncio
from collections.abc import Iterable
from dataclasses import field
from time import sleep, time

import grpc
import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.usage_ingestion.generated.usage_ingestion.v1 import service_pb2, service_pb2_grpc

logger = structlog.get_logger(__name__)

USAGE_INGESTION_RECORDS_SENT_TOTAL = Counter(
    "usage_ingestion_records_sent_total",
    "Usage records accepted by the usage-ingestion service.",
    labelnames=["producer_id", "usage_key"],
)

USAGE_INGESTION_RECORDS_FAILED_TOTAL = Counter(
    "usage_ingestion_records_failed_total",
    "Usage records dropped after the client exhausted its retries.",
    labelnames=["producer_id", "usage_key", "error_code"],
)

USAGE_INGESTION_RETRIES_TOTAL = Counter(
    "usage_ingestion_retries_total",
    "Ingest calls retried after a transient error.",
    labelnames=["producer_id", "error_code"],
)

RETRYABLE_CODES = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.CANCELLED,
        grpc.StatusCode.INTERNAL,
    }
)
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.1


@frozen
class UsageRecord:
    record_id: str
    producer_id: str
    team_id: int
    usage_key: str
    unit: str
    quantity: int
    # Emit time from our own clock. toDate of it is part of the storage sorting key, so a
    # value taken from customer data would decide whether these records deduplicate.
    timestamp_ms: int = field(default_factory=lambda: int(time() * 1000))


def team_is_enabled(team_id: int) -> bool:
    raw = os.environ.get("USAGE_INGESTION_REPORT_TEAMS", "").strip()
    return raw == "*" or str(team_id) in {value.strip() for value in raw.split(",") if value.strip()}


def _timeout_seconds() -> float:
    # The env var is milliseconds everywhere else, but grpc takes seconds.
    return float(os.environ.get("USAGE_INGESTION_TIMEOUT_MS", "5000")) / 1000


def _to_send(records: Iterable[UsageRecord]) -> tuple[list[UsageRecord], str]:
    return (
        [record for record in records if team_is_enabled(record.team_id)],
        os.environ.get("USAGE_INGESTION_ADDR", ""),
    )


def _request(records: list[UsageRecord]) -> service_pb2.IngestBillingUsageRequest:
    return service_pb2.IngestBillingUsageRequest(
        records=[
            service_pb2.BillingUsageRecord(
                record_id=record.record_id,
                producer_id=record.producer_id,
                team_id=record.team_id,
                usage_key=record.usage_key,
                unit=record.unit,
                quantity=record.quantity,
                timestamp_ms=record.timestamp_ms,
            )
            for record in records
        ]
    )


def _error_code(error: Exception) -> tuple[grpc.StatusCode | None, str]:
    if isinstance(error, grpc.RpcError):
        try:
            code = error.code()
            return code, code.name.replace("_", " ").title().replace(" ", "")
        except Exception:
            pass
    return None, "Unknown"


def _record_response(records: list[UsageRecord], response: service_pb2.IngestBillingUsageResponse) -> None:
    accepted = set(response.accepted_record_ids)
    for record in records:
        counter = (
            USAGE_INGESTION_RECORDS_SENT_TOTAL if record.record_id in accepted else USAGE_INGESTION_RECORDS_FAILED_TOTAL
        )
        labels = {"producer_id": record.producer_id, "usage_key": record.usage_key}
        if record.record_id not in accepted:
            labels["error_code"] = "rejected"
        counter.labels(**labels).inc()


def _record_failure(records: list[UsageRecord], error_code: str) -> None:
    for record in records:
        USAGE_INGESTION_RECORDS_FAILED_TOTAL.labels(
            producer_id=record.producer_id,
            usage_key=record.usage_key,
            error_code=error_code,
        ).inc()


def _retry_delay_seconds(records: list[UsageRecord], attempt: int, error: Exception) -> float:
    status, error_code = _error_code(error)
    if attempt + 1 < MAX_ATTEMPTS and status in RETRYABLE_CODES:
        USAGE_INGESTION_RETRIES_TOTAL.labels(producer_id=records[0].producer_id, error_code=error_code).inc()
        return RETRY_BACKOFF_SECONDS * 2**attempt
    _record_failure(records, error_code)
    raise error


# Every producer calls these after committing work of its own, and the nightly report is still
# the billing source of truth, so a record is worth less than the caller it runs in. Nothing
# escapes either function — not a bad address, not an unencodable field, not an RPC error.
# Building the request sits inside the try for that reason.


def report_usage(records: Iterable[UsageRecord], *, site: str) -> None:
    enabled: list[UsageRecord] = []
    try:
        enabled, address = _to_send(records)
        if not enabled or not address:
            return
        with grpc.insecure_channel(address) as channel:
            stub = service_pb2_grpc.UsageIngestionStub(channel)
            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = stub.IngestBillingUsage(
                        _request(enabled),
                        timeout=_timeout_seconds(),
                        metadata=(("x-client-name", enabled[0].producer_id),),
                    )
                    _record_response(enabled, response)
                    return
                except Exception as error:
                    sleep(_retry_delay_seconds(enabled, attempt, error))
    except Exception:
        logger.warning("usage_ingestion_report_failed", site=site, records=len(enabled), exc_info=True)


async def areport_usage(records: Iterable[UsageRecord], *, site: str) -> None:
    """Async variant, for producers already on an event loop.

    Prefer this to `asyncio.to_thread(report_usage, ...)`: that borrows a worker from the default
    executor, which a hot loop of `to_thread` calls has exhausted before.
    """
    enabled: list[UsageRecord] = []
    try:
        enabled, address = _to_send(records)
        if not enabled or not address:
            return
        async with grpc.aio.insecure_channel(address) as channel:
            stub = service_pb2_grpc.UsageIngestionStub(channel)
            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = await stub.IngestBillingUsage(
                        _request(enabled),
                        timeout=_timeout_seconds(),
                        metadata=(("x-client-name", enabled[0].producer_id),),
                    )
                    _record_response(enabled, response)
                    return
                except Exception as error:
                    await asyncio.sleep(_retry_delay_seconds(enabled, attempt, error))
    except Exception:
        logger.warning("usage_ingestion_report_failed", site=site, records=len(enabled), exc_info=True)
