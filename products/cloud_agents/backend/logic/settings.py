"""Project settings: the run defaults that apply when a call and its preset set no value."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from ..facade.contracts import CallerIdentity, InvalidInput, TeamSettingsDTO
from ..models import CloudAgentPreset, TeamCloudAgentsConfig
from .analytics import capture_event
from .config_resolution import validate_run_defaults
from .limits import DEFAULT_CREATE_RATE_PER_HOUR, DEFAULT_MAX_CONCURRENT_RUNS
from .run_defaults import RUN_DEFAULT_FIELDS, run_default_columns, run_defaults_of
from .team_config import get_team_config

# The limits are not here: staff set them.
SETTINGS_UPDATE_FIELDS: Final = RUN_DEFAULT_FIELDS | {"default_preset_id"}


def to_settings_dto(config: TeamCloudAgentsConfig) -> TeamSettingsDTO:
    return TeamSettingsDTO(
        default_preset_id=config.default_preset_id,
        max_concurrent_runs=(
            config.max_concurrent_runs if config.max_concurrent_runs is not None else DEFAULT_MAX_CONCURRENT_RUNS
        ),
        create_rate_per_hour=config.create_rate_per_hour or DEFAULT_CREATE_RATE_PER_HOUR,
        updated_at=config.updated_at,
        **run_defaults_of(config),
    )


def get_team_settings(team_id: int) -> TeamSettingsDTO:
    """Return the settings of the project. The first read creates the row with no defaults set."""
    return to_settings_dto(get_team_config(team_id))


def update_team_settings(team_id: int, changes: Mapping[str, Any], caller: CallerIdentity) -> TeamSettingsDTO:
    """Apply `changes`, a mapping of field name to new value. A None value clears a default."""
    unknown = set(changes) - SETTINGS_UPDATE_FIELDS
    if unknown:
        raise InvalidInput(f"These fields cannot be changed: {', '.join(sorted(unknown))}.")
    validate_run_defaults(changes)
    default_preset_id = changes.get("default_preset_id")
    if default_preset_id is not None:
        preset_exists = CloudAgentPreset.objects.for_team(team_id).filter(id=default_preset_id, deleted=False).exists()
        if not preset_exists:
            raise InvalidInput("This preset does not exist in this project.", attr="default_preset")

    config = get_team_config(team_id)
    columns = run_default_columns(changes)
    if "default_preset_id" in changes:
        columns["default_preset_id"] = default_preset_id
    for field, value in columns.items():
        setattr(config, field, value)
    if columns:
        config.save(update_fields=[*columns, "updated_at"])
        # Field names only. The values can hold instructions or a repository name.
        capture_event("cloud_agents_settings_updated", caller, team_id, {"changed_fields": sorted(columns)})
    return to_settings_dto(config)
