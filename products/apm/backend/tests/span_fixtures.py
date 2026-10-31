"""Shared ClickHouse fixtures for the APM API tests: a trace_spans table with is_root_span, and a span writer."""

import base64
import datetime as dt
from dataclasses import dataclass, field

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def recreate_trace_spans_tables() -> None:
    # is_root_span ships via a separate logs-cluster migration, not the Python DDL.
    sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
    sync_execute("DROP TABLE IF EXISTS trace_spans")
    sync_execute(TRACE_SPANS_TABLE_SQL())
    sync_execute(
        "ALTER TABLE trace_spans ADD COLUMN IF NOT EXISTS "
        "is_root_span Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = ''"
    )
    sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())


def restore_trace_spans_tables() -> None:
    sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
    sync_execute("DROP TABLE IF EXISTS trace_spans")
    sync_execute(TRACE_SPANS_TABLE_SQL())
    sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())


@dataclass(frozen=False)
class SpanWriter:
    """Builds span rows for one team and inserts them in one statement.

    `span()` returns the new span's id so a caller can hang children off it.
    """

    team_id: int
    base: dt.datetime
    uuid_prefix: str = "019e8772"
    rows: list[str] = field(default_factory=list)
    n: int = 0

    def span(
        self,
        service: str,
        *,
        name: str = "op",
        kind: int = 2,
        status_code: int = 0,
        ms: int = 10,
        env: str = "",
        trace: int | None = None,
        parent: str = "",
    ) -> str:
        self.n += 1
        span_id = b64(self.n.to_bytes(8, "big"))
        trace_id = b64((trace if trace is not None else self.n).to_bytes(16, "big"))
        start = self.base + dt.timedelta(seconds=self.n)
        end = start + dt.timedelta(milliseconds=ms)
        attrs = f"map('deployment.environment.name', '{env}')" if env else "map()"
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        self.rows.append(
            f"('{self.uuid_prefix}-0000-0000-0000-{self.n:012d}', {self.team_id}, '{trace_id}', '{span_id}', "
            f"'{parent}', '{name}', {kind}, '{start.strftime(fmt)}', '{end.strftime(fmt)}', '{start.strftime(fmt)}', "
            f"{status_code}, '{service}', {attrs})"
        )
        return span_id

    def insert(self) -> None:
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, resource_attributes) VALUES "
            + ",".join(self.rows)
        )
        self.rows.clear()
