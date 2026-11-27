"""Which answer engines a project runs, and how often.

A project only has rows for the engines someone changed; every other engine runs with its default
from `ENGINE_SPECS`. An engine this deployment cannot run (no API key, or a gate that is off) never
runs, whatever its setting says.
"""

from __future__ import annotations

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.engines import ENGINE_SPECS, ENGINE_SPECS_BY_ID, CitationEngine
from products.aeo.backend.facade.contracts import (
    CheckFrequency,
    EngineNotFoundError,
    EngineSetting,
    EngineSettingUpdate,
)
from products.aeo.backend.models import AEOEngineSetting

PERIOD_DAYS: dict[CheckFrequency, int] = {CheckFrequency.EVERY_3_DAYS: 3, CheckFrequency.WEEKLY: 7}


@frozen
class EngineSchedule:
    daily: tuple[CitationEngine, ...]
    weekly: tuple[CitationEngine, ...]
    periods: dict[str, int]


def list_engine_settings(team_id: int) -> list[EngineSetting]:
    rows = {row.engine: row for row in AEOEngineSetting.objects.for_team(team_id)}
    settings_list: list[EngineSetting] = []
    for spec in ENGINE_SPECS:
        row = rows.get(spec.engine)
        settings_list.append(
            EngineSetting(
                engine=spec.engine,
                mode=spec.mode,
                available=spec.is_configured(),
                enabled=row.enabled if row else spec.default_enabled,
                frequency=CheckFrequency(row.frequency) if row else CheckFrequency.DAILY,
            )
        )
    return settings_list


def update_engine_setting(team_id: int, engine: str, change: EngineSettingUpdate) -> EngineSetting:
    """Raises EngineNotFoundError for an engine id this product does not know."""
    spec = ENGINE_SPECS_BY_ID.get(engine)
    if spec is None:
        raise EngineNotFoundError(engine)
    current = next(setting for setting in list_engine_settings(team_id) if setting.engine == engine)
    enabled = current.enabled if change.enabled is None else change.enabled
    frequency = current.frequency if change.frequency is None else change.frequency
    AEOEngineSetting.objects.for_team(team_id).update_or_create(
        engine=engine,
        defaults={"enabled": enabled, "frequency": frequency.value},
        create_defaults={
            "team_id": resolve_effective_team_id(team_id),
            "enabled": enabled,
            "frequency": frequency.value,
        },
    )
    return EngineSetting(
        engine=engine, mode=spec.mode, available=spec.is_configured(), enabled=enabled, frequency=frequency
    )


def engine_schedule(team_id: int) -> EngineSchedule:
    """The engines the project runs, split by frequency, among the ones this deployment can run."""
    enabled = [setting for setting in list_engine_settings(team_id) if setting.enabled and setting.available]
    spread = [s for s in enabled if s.frequency in PERIOD_DAYS]
    return EngineSchedule(
        daily=tuple(ENGINE_SPECS_BY_ID[s.engine].build() for s in enabled if s.frequency == CheckFrequency.DAILY),
        weekly=tuple(ENGINE_SPECS_BY_ID[s.engine].build() for s in spread),
        periods={s.engine: PERIOD_DAYS[s.frequency] for s in spread},
    )
