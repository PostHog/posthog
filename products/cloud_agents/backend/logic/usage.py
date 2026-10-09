"""Usage totals of a project, from the charges that Tasks reports for the tasks of its runs."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.facade.cloud_agents import summarize_cloud_agent_usage
from products.tasks.backend.facade.contracts import CloudAgentTaskUsageDTO

from ..facade.contracts import InvalidInput, UsageBucketDTO, UsageSummaryDTO, UsageTotalsDTO
from ..facade.enums import UsageGroupBy
from ..models import CloudAgentRun
from .cost import cents_to_usd, inference_usd

logger = structlog.get_logger(__name__)

DEFAULT_RANGE: Final = timedelta(days=30)
MAX_RANGE: Final = timedelta(days=366)
# The summary covers the newest runs of the range up to this number.
MAX_RUNS_IN_SUMMARY: Final = 2000


@frozen
class _Preset:
    id: UUID
    name: str


def _totals(rows: Iterable[CloudAgentTaskUsageDTO]) -> UsageTotalsDTO:
    runs = 0
    compute_usd = Decimal(0)
    inference_cost_usd = Decimal(0)
    vcpu_seconds = Decimal(0)
    gib_seconds = Decimal(0)
    for row in rows:
        runs += 1
        compute_usd += cents_to_usd(row.compute_cost_cents) or Decimal(0)
        inference_cost_usd += inference_usd(row.inference_cost_cents, row.inference_billing) or Decimal(0)
        vcpu_seconds += row.vcpu_seconds
        gib_seconds += row.gib_seconds
    return UsageTotalsDTO(
        runs=runs,
        compute_usd=compute_usd,
        inference_usd=inference_cost_usd,
        total_usd=compute_usd + inference_cost_usd,
        vcpu_seconds=vcpu_seconds.quantize(Decimal("0.001")),
        gib_seconds=gib_seconds.quantize(Decimal("0.001")),
    )


def _grouped[Key: Hashable](
    rows: Iterable[CloudAgentTaskUsageDTO], key_of: dict[UUID, Key]
) -> dict[Key, list[CloudAgentTaskUsageDTO]]:
    groups: dict[Key, list[CloudAgentTaskUsageDTO]] = {}
    for row in rows:
        groups.setdefault(key_of[row.task_id], []).append(row)
    return groups


def _day_buckets(rows: tuple[CloudAgentTaskUsageDTO, ...]) -> list[UsageBucketDTO]:
    by_day = _grouped(rows, {row.task_id: row.created_at.astimezone(UTC).date() for row in rows})
    return [UsageBucketDTO(key=day.isoformat(), label=None, usage=_totals(by_day[day])) for day in sorted(by_day)]


def _preset_buckets(team_id: int, rows: tuple[CloudAgentTaskUsageDTO, ...]) -> list[UsageBucketDTO]:
    preset_of_task: dict[UUID, _Preset | None] = {row.task_id: None for row in rows}
    runs = CloudAgentRun.objects.for_team(team_id).filter(task_id__in=list(preset_of_task), preset__isnull=False)
    for task_id, preset_id, preset_name in runs.values_list("task_id", "preset_id", "preset__name"):
        if task_id is not None:
            preset_of_task[task_id] = _Preset(id=preset_id, name=preset_name)
    by_preset = _grouped(rows, preset_of_task)
    # The runs with no preset are the last bucket.
    presets = sorted((preset for preset in by_preset if preset is not None), key=lambda p: (p.name, str(p.id)))
    buckets = [
        UsageBucketDTO(key=str(preset.id), label=preset.name, usage=_totals(by_preset[preset])) for preset in presets
    ]
    if None in by_preset:
        buckets.append(UsageBucketDTO(key=None, label=None, usage=_totals(by_preset[None])))
    return buckets


def get_usage_summary(
    team_id: int, *, date_from: datetime | None, date_to: datetime | None, group_by: UsageGroupBy
) -> UsageSummaryDTO:
    """Totals and buckets for the runs created from `date_from` up to, and not at, `date_to`."""
    date_to = date_to or datetime.now(tz=UTC)
    date_from = date_from or date_to - DEFAULT_RANGE
    if date_from >= date_to:
        raise InvalidInput("The start of the range must be before its end.", attr="date_from")
    if date_to - date_from > MAX_RANGE:
        raise InvalidInput(f"The range must be {MAX_RANGE.days} days or less.", attr="date_from")
    usage = summarize_cloud_agent_usage(
        team_id=team_id, date_from=date_from, date_to=date_to, limit=MAX_RUNS_IN_SUMMARY
    )
    if usage.truncated:
        logger.warning("cloud_agents_usage_summary_truncated", team_id=team_id, limit=MAX_RUNS_IN_SUMMARY)
    buckets = _day_buckets(usage.rows) if group_by == UsageGroupBy.DAY else _preset_buckets(team_id, usage.rows)
    return UsageSummaryDTO(
        date_from=date_from, date_to=date_to, group_by=group_by, totals=_totals(usage.rows), buckets=buckets
    )
