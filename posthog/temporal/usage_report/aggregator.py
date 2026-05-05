"""Pure-logic helpers for the aggregation step.

Keeps Temporal / IO concerns out of the way: this module only knows how to
turn S3-backed query results into the legacy `all_data` shape, fan multi-key
queries back out into their destination keys, and shape per-organization
JSONL lines for the chunked output. Activities import from here.
"""

import itertools
from collections.abc import Iterable, Iterator
from typing import Any

from django.conf import settings

from posthog.tasks.usage_report import (
    InstanceMetadata,
    OrgReport,
    convert_team_usage_rows_to_dict,
    serialize_full_org_report,
)
from posthog.temporal.usage_report.queries import QUERY_INDEX
from posthog.temporal.usage_report.storage import bucket, read_json
from posthog.temporal.usage_report.types import Manifest, RunQueryToS3Result, WorkflowContext


def load_all_data(query_results: list[RunQueryToS3Result]) -> dict[str, dict[int, int]]:
    """Reconstruct the legacy `all_data` map from per-query S3 files.

    Single-output specs become one entry keyed by `spec.name`. Multi-output
    specs are fanned out into the destination keys defined in their
    `multi_keys_mapping` so downstream code sees the same flat shape the
    Celery path produces today.
    """
    all_data: dict[str, dict[int, int]] = {}
    for result in query_results:
        spec = QUERY_INDEX[result.query_name]
        raw = read_json(result.s3_key)
        if spec.output == "multi":
            for source_key, dest_key in spec.multi_keys_mapping.items():
                rows = raw.get(source_key, [])
                all_data[dest_key] = convert_team_usage_rows_to_dict(rows)
        else:
            all_data[spec.name] = convert_team_usage_rows_to_dict(raw)
    return all_data


def iter_chunk_lines(
    org_reports: Iterable[OrgReport],
    instance_metadata: InstanceMetadata,
) -> Iterator[tuple[dict[str, Any], bool]]:
    """Yield `(line_dict, has_non_zero_usage)` for each org report.

    `line_dict` is the JSONL line that ends up in S3 (and is what billing
    consumes). The boolean lets the caller count non-zero orgs without a
    second pass over the dict.
    """
    for org_report in org_reports:
        report_dict = serialize_full_org_report(org_report, instance_metadata)
        line = {
            "organization_id": org_report.organization_id,
            "usage_report": report_dict,
        }
        yield line, bool(report_dict.get("has_non_zero_usage"))


def batched(iterable: Iterable[Any], size: int) -> Iterator[list[Any]]:
    """Local `itertools.batched` so the module stays usable on 3.11."""
    if size <= 0:
        raise ValueError("batch size must be positive")
    it = iter(iterable)
    while True:
        batch = list(itertools.islice(it, size))
        if not batch:
            return
        yield batch


def build_manifest(
    ctx: WorkflowContext,
    chunk_keys: list[str],
    total_orgs: int,
    total_orgs_with_usage: int,
    region: str,
    *,
    version: int,
) -> Manifest:
    """Build the typed manifest billing reads after the SQS pointer arrives."""
    return Manifest(
        version=version,
        run_id=ctx.run_id,
        date=ctx.date_str,
        period_start=ctx.period_start,
        period_end=ctx.period_end,
        region=region,
        site_url=settings.SITE_URL,
        bucket=bucket(),
        chunk_keys=chunk_keys,
        chunk_count=len(chunk_keys),
        total_orgs=total_orgs,
        total_orgs_with_usage=total_orgs_with_usage,
    )


def filter_org_reports(
    org_reports: dict[str, OrgReport],
    organization_ids: list[str] | None,
) -> dict[str, OrgReport]:
    """Apply the optional `organization_ids` filter from workflow inputs."""
    if not organization_ids:
        return org_reports
    wanted = set(organization_ids)
    return {oid: report for oid, report in org_reports.items() if oid in wanted}


def sort_org_reports(org_reports: dict[str, OrgReport]) -> list[OrgReport]:
    """Deterministic ordering so chunk contents are stable across retries."""
    return sorted(org_reports.values(), key=lambda r: r.organization_id)
