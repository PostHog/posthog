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
    acked_watermark: str | None = None
    # Duckgres was ahead of our recorded ack — persisted this window but did not
    # ack (possible lost usage; alerted for reconciliation).
    watermark_hole: bool = False
