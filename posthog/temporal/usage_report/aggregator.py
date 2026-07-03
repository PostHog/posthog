"""Helpers for the aggregation step of the Temporal usage-reports flow.

Most of this module is pure logic — turning S3-backed query results into the
legacy `all_data` shape, fanning multi-key queries back out into their
destination keys, and shaping per-organization JSONL lines for the chunked
output. The Temporal-local replacement for the legacy `build_org_reports`
also lives here so the activity can drive aggregation without touching the
Celery code path; that one bulk-fetches `OrganizationMembership` counts so
the per-org `count()` N+1 in the legacy helper never fires for Temporal.
Activities import from here.
"""

import itertools
import dataclasses
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db.models import Count

from posthog.models import OrganizationMembership, Team
from posthog.tasks.usage_report import (
    InstanceMetadata,
    OrgReport,
    UsageReportCounters,
    _get_team_report,
    _get_teams_for_usage_reports,
    convert_team_usage_rows_to_dict,
    has_non_zero_usage,
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
) -> Iterator[dict[str, Any]]:
    """Yield the JSONL line dict billing consumes for each org report.

    Filtering by `has_non_zero_usage` happens upstream in the activity, so
    everything yielded here is expected to have usage.
    """
    for org_report in org_reports:
        report_dict = serialize_full_org_report(org_report, instance_metadata)
        yield {
            "organization_id": org_report.organization_id,
            "usage_report": report_dict,
        }


def filter_orgs_with_usage(org_reports: dict[str, OrgReport]) -> dict[str, OrgReport]:
    """Drop org reports with no billable usage before serialization. Reuses
    the legacy `has_non_zero_usage` directly on `OrgReport`s — every field
    it checks lives on `UsageReportCounters`, the base class shared by
    `OrgReport` and `FullUsageReport`, so we skip the
    `dataclasses.asdict(FullUsageReport)` round-trip the legacy path forces.
    Skipping that on the >99% of orgs without usage is the dominant CPU
    win in the aggregation activity.
    """
    return {oid: report for oid, report in org_reports.items() if has_non_zero_usage(report)}


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
        day_offset=ctx.day_offset,
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


def get_org_user_counts() -> dict[str, int]:
    """Bulk membership count per organization, keyed by `str(org_id)`.

    The legacy `_add_team_report_to_org_reports` runs one
    `OrganizationMembership.count()` per organization inside its team loop,
    which dominated the aggregation activity's wall-clock at ~50k orgs. The
    Temporal flow fetches the whole map once up front and looks up by
    `str(org_id)`. Orgs without memberships are absent — callers default to
    0. We keep this off the Celery path on purpose; that path still uses
    the per-org helper.
    """
    # `.iterator()` skips Django's QuerySet result cache, so we don't hold
    # the full list of rows alongside the dict we're building. `chunk_size`
    # just tunes the server-side cursor batch.
    return {
        str(row["organization_id"]): row["count"]
        for row in OrganizationMembership.objects.values("organization_id")
        .annotate(count=Count("id"))
        .iterator(chunk_size=10_000)
    }


def build_org_reports(
    all_data: dict[str, Any],
    period_start: datetime,
    org_user_counts: dict[str, int],
) -> dict[str, OrgReport]:
    """Temporal-local replacement for `posthog.tasks.usage_report.build_org_reports`.

    Same shape and semantics as the legacy facade, but takes a pre-fetched
    `org_user_counts` dict instead of issuing one Postgres `count()` per
    organization. The legacy facade is intentionally left untouched so the
    Celery flow's behavior is preserved — the parity tests pin both paths
    against each other.
    """
    org_reports: dict[str, OrgReport] = {}
    for team in _get_teams_for_usage_reports():
        team_report = _get_team_report(all_data, team)
        _add_team_report_to_org_reports(org_reports, team, team_report, period_start, org_user_counts)
    return org_reports


def _add_team_report_to_org_reports(
    org_reports: dict[str, OrgReport],
    team: Team,
    team_report: UsageReportCounters,
    period_start: datetime,
    org_user_counts: dict[str, int],
) -> None:
    """Mirror of `posthog.tasks.usage_report._add_team_report_to_org_reports`
    that reads `organization_user_count` from the bulk dict instead of the
    per-org Postgres helper. Behavior is otherwise identical.
    """
    org_id = str(team.organization.id)
    if org_id not in org_reports:
        org_report = OrgReport(
            date=period_start.strftime("%Y-%m-%d"),
            organization_id=org_id,
            organization_name=team.organization.name,
            organization_created_at=team.organization.created_at.isoformat(),
            organization_user_count=org_user_counts.get(org_id, 0),
            team_count=1,
            teams={str(team.id): team_report},
            **dataclasses.asdict(team_report),  # Clone the team report as the basis
        )
        org_reports[org_id] = org_report
    else:
        org_report = org_reports[org_id]
        org_report.teams[str(team.id)] = team_report
        org_report.team_count += 1

        for field in dataclasses.fields(UsageReportCounters):
            if hasattr(team_report, field.name):
                setattr(
                    org_report,
                    field.name,
                    getattr(org_report, field.name) + getattr(team_report, field.name),
                )
