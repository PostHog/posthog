"""Workflow + activity input/output models.

All models use pydantic so the Temporal pydantic data converter handles
`datetime` (and other rich types) natively — that lets us drop the
ISO-string round-tripping that plain dataclasses would force.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RunUsageReportsInputs(BaseModel):
    """Top-level workflow input."""

    at: Optional[str] = None
    organization_ids: Optional[list[str]] = None


class WorkflowContext(BaseModel):
    """Snapshot of the workflow run, threaded through every activity."""

    run_id: str
    period_start: datetime
    period_end: datetime
    date_str: str
    organization_ids: Optional[list[str]] = None


class RunQueryToS3Inputs(BaseModel):
    ctx: WorkflowContext
    query_name: str


class RunQueryToS3Result(BaseModel):
    query_name: str
    s3_key: str
    duration_ms: int


class AggregateInputs(BaseModel):
    ctx: WorkflowContext
    query_results: list[RunQueryToS3Result]


class Manifest(BaseModel):
    """Manifest written next to the JSONL chunks. Billing reads this to
    discover the chunk list and run metadata before streaming the chunks.
    """

    version: int
    run_id: str
    date: str
    period_start: datetime
    period_end: datetime
    region: str
    site_url: str
    bucket: str
    chunk_keys: list[str]
    chunk_count: int
    total_orgs: int
    total_orgs_with_usage: int


class AggregateResult(BaseModel):
    chunk_keys: list[str]
    manifest_key: str
    total_orgs: int
    total_orgs_with_usage: int


class EnqueuePointerInputs(BaseModel):
    ctx: WorkflowContext
    aggregate: AggregateResult


class CleanupInputs(BaseModel):
    ctx: WorkflowContext
    query_keys: list[str]
