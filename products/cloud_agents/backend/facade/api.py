"""
Facade for cloud_agents.

The ONLY module other products and the presentation layer are allowed to import.
Accept and return the frozen dataclasses in contracts.py. Never return ORM
instances or import DRF.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from ..logic import (
    catalog as catalog_logic,
    config_resolution,
    limits as limits_logic,
    presets as presets_logic,
    runs as runs_logic,
    settings as settings_logic,
    streams as streams_logic,
    usage as usage_logic,
)
from .contracts import (
    CallerIdentity,
    CatalogDTO,
    EstimateDTO,
    MessageResult,
    PresetCreateInput,
    PresetDTO,
    ResolvedRunConfig,
    RunCreateInput,
    RunDTO,
    RunEventsDTO,
    RunEventStream,
    RunListFilters,
    RunUsageDTO,
    TeamSettingsDTO,
    UsageSummaryDTO,
)
from .enums import SizeName, UsageGroupBy

MIN_IDLE_MINUTES = config_resolution.MIN_IDLE_MINUTES
MAX_IDLE_MINUTES = config_resolution.MAX_IDLE_MINUTES


# --- Run configuration ---


def resolve_run_config(call: RunCreateInput, preset: PresetDTO | None, team: TeamSettingsDTO) -> ResolvedRunConfig:
    return config_resolution.resolve_run_config(call, preset, team)


def render_prompt(config: ResolvedRunConfig, prompt: str) -> str:
    return config_resolution.render_prompt(config, prompt)


# --- Runs ---


def start_run(
    team_id: int, caller: CallerIdentity, data: RunCreateInput, idempotency_key: str | None = None
) -> tuple[RunDTO, bool]:
    """Start a run. The flag is True when the idempotency key replayed a run that an earlier request started.

    Another product calls this with `CallerIdentity(kind=CallerKind.INTERNAL, billable=False, product=...)`
    to start a run that the project is not billed for.
    """
    return runs_logic.start_run(team_id, caller, data, idempotency_key)


def get_run(team_id: int, run_id: UUID) -> RunDTO:
    return runs_logic.get_run(team_id, run_id)


def list_runs(team_id: int, filters: RunListFilters | None = None) -> Sequence[RunDTO]:
    """The runs of the project, newest first. The result reads only the page that the caller takes a slice of."""
    return runs_logic.list_runs(team_id, filters or RunListFilters())


def send_message(team_id: int, caller: CallerIdentity, run_id: UUID, content: str) -> MessageResult:
    return runs_logic.send_message(team_id, caller, run_id, content)


def cancel_run(team_id: int, caller: CallerIdentity, run_id: UUID) -> tuple[RunDTO, bool]:
    """Ask the run to stop. The flag is False when the run has no agent at work."""
    return runs_logic.cancel_run(team_id, caller, run_id)


def get_run_usage(team_id: int, run_id: UUID) -> RunUsageDTO:
    return runs_logic.get_run_usage(team_id, run_id)


def get_run_events(team_id: int, run_id: UUID) -> RunEventsDTO:
    return runs_logic.get_run_events(team_id, run_id)


def prepare_run_event_stream(
    team_id: int, run_id: UUID, *, last_event_id: str | None, start_latest: bool
) -> RunEventStream:
    """Resolve the run for streaming. It reads the database, so call it on the request thread."""
    return streams_logic.prepare_run_event_stream(
        team_id, run_id, last_event_id=last_event_id, start_latest=start_latest
    )


def run_event_stream(stream: RunEventStream) -> AsyncGenerator[bytes]:
    """The body of the stream response, as Server-Sent Events frames."""
    return streams_logic.run_event_stream(stream)


# --- Catalog and usage ---


def get_catalog(team_id: int) -> CatalogDTO:
    return catalog_logic.get_catalog(team_id)


def estimate_cost(size: SizeName, minutes: int) -> EstimateDTO:
    return catalog_logic.estimate_cost(size, minutes)


def get_usage_summary(
    team_id: int, *, date_from: datetime | None, date_to: datetime | None, group_by: UsageGroupBy
) -> UsageSummaryDTO:
    return usage_logic.get_usage_summary(team_id, date_from=date_from, date_to=date_to, group_by=group_by)


# --- Presets ---


def list_presets(team_id: int) -> list[PresetDTO]:
    return presets_logic.list_presets(team_id)


def get_preset(team_id: int, preset_id: UUID) -> PresetDTO:
    return presets_logic.get_preset(team_id, preset_id)


def get_preset_by_ref(team_id: int, ref: str) -> PresetDTO:
    return presets_logic.get_preset_by_ref(team_id, ref)


def create_preset(team_id: int, data: PresetCreateInput, caller: CallerIdentity) -> PresetDTO:
    return presets_logic.create_preset(team_id, data, caller)


def update_preset(team_id: int, preset_id: UUID, changes: Mapping[str, Any], caller: CallerIdentity) -> PresetDTO:
    return presets_logic.update_preset(team_id, preset_id, changes, caller)


def delete_preset(team_id: int, preset_id: UUID, caller: CallerIdentity) -> None:
    presets_logic.delete_preset(team_id, preset_id, caller)


# --- Project settings ---


def get_team_settings(team_id: int) -> TeamSettingsDTO:
    return settings_logic.get_team_settings(team_id)


def update_team_settings(team_id: int, changes: Mapping[str, Any], caller: CallerIdentity) -> TeamSettingsDTO:
    return settings_logic.update_team_settings(team_id, changes, caller)


# --- Limits ---


def concurrency_guard(team_id: int, count_active: Callable[[], int]) -> None:
    limits_logic.concurrency_guard(team_id, count_active)


def consume_create_rate(team_id: int) -> None:
    limits_logic.consume_create_rate(team_id)


def refund_create_rate(team_id: int) -> None:
    limits_logic.refund_create_rate(team_id)
