"""Helpers for the aggregation step of the Temporal usage-reports flow.

Most of this module is pure logic — turning S3-backed query results into the
legacy `all_data` shape, fanning multi-key queries back out into their
destination keys, and shaping per-organization JSONL lines for the chunked
output. `iter_org_reports` streams one report per organization without
touching the Celery code path. It reads `OrganizationMembership` counts from
one bulk query, so the per-org `count()` N+1 in the legacy helper never fires
for Temporal. Activities import from here.
"""

import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timedelta
from itertools import chain, groupby, islice
from typing import Any

from django.conf import settings
from django.db.models import Count

from pydantic import TypeAdapter

from posthog.models import OrganizationMembership, Team
from posthog.tasks.usage_report import (
    InstanceMetadata,
    OrgReport,
    UsageReportCounters,
    _get_team_report,
    _get_teams_for_usage_reports,
    convert_team_usage_rows_to_dict,
    has_non_zero_usage,
    iter_reports_with_offline_evaluation_usage,
    serialize_full_org_report,
)
from posthog.temporal.usage_report.queries import QUERY_INDEX
from posthog.temporal.usage_report.storage import (
    bucket,
    chunk_key,
    manifest_key,
    read_json,
    write_json,
    write_jsonl_chunk_gzip,
)
from posthog.temporal.usage_report.types import (
    AggregateInputs,
    AggregateResult,
    Manifest,
    RunQueryToS3Result,
    WorkflowContext,
)
from posthog.usage_counters import UsageCounterReport

from products.ai_observability.backend.offline_evaluation_billing import get_offline_evaluation_usage

_SANDBOX_COMPUTE_QUERY_NAME = "sandbox_compute_usage"
_SANDBOX_COMPUTE_DESTINATION_KEYS = (
    "teams_with_sandbox_compute_credits_used_in_period",
    "teams_with_sandbox_compute_cpu_millicore_seconds_in_period",
    "teams_with_sandbox_compute_memory_mib_seconds_in_period",
)
_LOGS_DISTINCT_PATTERNS_QUERY_NAME = "teams_with_logs_distinct_patterns_in_period"
_TRANSACTIONAL_EMAILS_QUERY_NAME = "teams_with_workflow_transactional_emails_sent_in_period"
_MCP_EVENT_COUNT_QUERY_NAME = "teams_with_mcp_event_count_in_period"
_REPLAY_VISION_SPEND_PROJECTION_QUERY_NAME = "replay_vision_spend_projection"
_REPLAY_VISION_SPEND_PROJECTION_DESTINATION_KEYS = (
    "teams_with_replay_vision_scanner_projected_credits",
    "teams_with_replay_vision_backfill_committed_credits",
)


def load_usage_counter_report(inputs: AggregateInputs) -> UsageCounterReport:
    if inputs.counter_result is None:
        if inputs.ctx.usage_counter_plan is not None:
            raise ValueError("The usage counter report is missing")
        return UsageCounterReport(counts={})
    return TypeAdapter(UsageCounterReport).validate_python(read_json(inputs.counter_result.s3_key))


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


def add_pre_sandbox_compute_patch_defaults(
    all_data: dict[str, dict[int, int]], query_results: list[RunQueryToS3Result]
) -> None:
    if not any(result.query_name == _SANDBOX_COMPUTE_QUERY_NAME for result in query_results):
        for key in _SANDBOX_COMPUTE_DESTINATION_KEYS:
            all_data[key] = {}


def add_pre_logs_distinct_patterns_patch_defaults(
    all_data: dict[str, dict[int, int]], query_results: list[RunQueryToS3Result]
) -> None:
    if not any(result.query_name == _LOGS_DISTINCT_PATTERNS_QUERY_NAME for result in query_results):
        all_data[_LOGS_DISTINCT_PATTERNS_QUERY_NAME] = {}


def add_pre_transactional_emails_patch_defaults(
    all_data: dict[str, dict[int, int]], query_results: list[RunQueryToS3Result]
) -> None:
    if not any(result.query_name == _TRANSACTIONAL_EMAILS_QUERY_NAME for result in query_results):
        all_data[_TRANSACTIONAL_EMAILS_QUERY_NAME] = {}


def add_pre_mcp_event_count_patch_defaults(
    all_data: dict[str, dict[int, int]], query_results: list[RunQueryToS3Result]
) -> None:
    if not any(result.query_name == _MCP_EVENT_COUNT_QUERY_NAME for result in query_results):
        all_data[_MCP_EVENT_COUNT_QUERY_NAME] = {}


def add_pre_replay_vision_spend_projection_patch_defaults(
    all_data: dict[str, dict[int, int]], query_results: list[RunQueryToS3Result]
) -> None:
    if not any(result.query_name == _REPLAY_VISION_SPEND_PROJECTION_QUERY_NAME for result in query_results):
        for key in _REPLAY_VISION_SPEND_PROJECTION_DESTINATION_KEYS:
            all_data[key] = {}


def iter_chunk_lines(
    org_reports: Iterable[OrgReport],
    instance_metadata: InstanceMetadata,
) -> Iterator[dict[str, Any]]:
    """Yield the JSONL line dict billing consumes for each org report.

    `write_org_report_chunks` drops reports without usage before this step,
    so every report here has usage.
    """
    for org_report in org_reports:
        report_dict = serialize_full_org_report(org_report, instance_metadata)
        yield {
            "organization_id": org_report.organization_id,
            "usage_report": report_dict,
        }


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
        report_completeness=ctx.report_completeness,
        region=region,
        site_url=settings.SITE_URL,
        bucket=bucket(),
        chunk_keys=chunk_keys,
        chunk_count=len(chunk_keys),
        total_orgs=total_orgs,
        total_orgs_with_usage=total_orgs_with_usage,
    )


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


def _iter_ingested_org_reports(
    all_data: dict[str, dict[int, int]],
    ctx: WorkflowContext,
    org_user_counts: dict[str, int],
) -> Iterator[OrgReport]:
    teams = _get_teams_for_usage_reports(organization_ids=ctx.organization_ids)
    for organization_id, org_teams in groupby(teams, key=lambda team: team.organization_id):
        org_id = str(organization_id)
        org_reports: dict[str, OrgReport] = {}
        for team in org_teams:
            team_report = _get_team_report(all_data, team)
            _add_team_report_to_org_reports(org_reports, team, team_report, ctx.period_start, org_user_counts)
        yield org_reports[org_id]


def iter_org_reports(
    all_data: dict[str, dict[int, int]],
    ctx: WorkflowContext,
    org_user_counts: dict[str, int],
) -> Iterator[OrgReport]:
    offline_usage = get_offline_evaluation_usage(ctx.period_start, ctx.period_start + timedelta(days=1))
    yield from iter_reports_with_offline_evaluation_usage(
        _iter_ingested_org_reports(all_data, ctx, org_user_counts),
        offline_usage,
        ctx.period_start,
        organization_ids=ctx.organization_ids,
    )


def write_org_report_chunks(
    ctx: WorkflowContext,
    org_reports: Iterable[OrgReport],
    instance_metadata: InstanceMetadata,
    *,
    chunk_size: int,
    version: int,
    region: str,
    check_cancelled: Callable[[], None],
) -> AggregateResult:
    total_orgs = 0
    total_orgs_with_usage = 0

    def reports_with_usage() -> Iterator[OrgReport]:
        nonlocal total_orgs, total_orgs_with_usage
        for report in org_reports:
            check_cancelled()
            total_orgs += 1
            if has_non_zero_usage(report):
                total_orgs_with_usage += 1
                yield report

    lines = iter_chunk_lines(reports_with_usage(), instance_metadata)
    chunk_keys: list[str] = []
    while (first_line := next(lines, None)) is not None:
        key = chunk_key(ctx, len(chunk_keys))
        write_jsonl_chunk_gzip(key, chain((first_line,), islice(lines, chunk_size - 1)))
        chunk_keys.append(key)

    check_cancelled()
    manifest = build_manifest(
        ctx,
        chunk_keys=chunk_keys,
        total_orgs=total_orgs,
        total_orgs_with_usage=total_orgs_with_usage,
        region=region,
        version=version,
    )
    m_key = manifest_key(ctx)
    write_json(m_key, manifest.model_dump(mode="json"))
    return AggregateResult(
        chunk_keys=chunk_keys,
        manifest_key=m_key,
        total_orgs=total_orgs,
        total_orgs_with_usage=total_orgs_with_usage,
    )
