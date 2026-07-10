"""Workflow/activity payload models for the duckgres usage poller.

Pydantic (not dataclasses) to match the usage_report module's convention: the
Temporal pydantic data converter handles datetimes natively, and new fields
must be Optional-with-default so in-flight payloads decode across deploys.
"""

from pydantic import BaseModel


class PollDuckgresUsageInputs(BaseModel):
    """No knobs yet — exists so future fields don't change the wire shape."""


class PollDuckgresUsageResult(BaseModel):
    skipped: bool = False
    rows_written: int = 0
    watermark_low: str | None = None
    watermark_high: str | None = None
    # The watermark this pull should ack (None when nothing closed, or when we
    # deliberately withhold the ack — see watermark_hole / unparsed_row_count).
    # The poll activity records it; the workflow performs the ack.
    ack_watermark: str | None = None
    # Duckgres was ahead of our recorded ack — persisted this window but withheld
    # the ack (possible lost usage; alerted for reconciliation).
    watermark_hole: bool = False
    # Rows that failed to parse and were dropped. Non-zero withholds the ack so
    # duckgres keeps the un-parsed data until the upstream cause is fixed.
    unparsed_row_count: int = 0
