import os
from collections.abc import Iterable
from dataclasses import field
from time import time

import grpc
import structlog

from posthog.dataclasses import frozen
from posthog.usage_ingestion.generated.usage_ingestion.v1 import service_pb2, service_pb2_grpc

logger = structlog.get_logger(__name__)


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


def report_usage(records: Iterable[UsageRecord], *, site: str) -> None:
    enabled = [record for record in records if team_is_enabled(record.team_id)]
    address = os.environ.get("USAGE_INGESTION_ADDR", "")
    if not enabled or not address:
        return

    # Every producer calls this after committing work of its own, and the nightly report is
    # still the billing source of truth, so a record is worth less than the caller it runs in.
    # Nothing here escapes — not a bad address, not an unencodable field, not an RPC error.
    try:
        request = service_pb2.IngestBillingUsageRequest(
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
                for record in enabled
            ]
        )
        with grpc.insecure_channel(address) as channel:
            service_pb2_grpc.UsageIngestionStub(channel).IngestBillingUsage(request, timeout=_timeout_seconds())
    except Exception:
        logger.warning("usage_ingestion_report_failed", site=site, records=len(enabled), exc_info=True)
