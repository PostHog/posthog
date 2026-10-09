"""Presets: named sets of run defaults that a run can use with only a prompt."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.db.models.functions import Lower
from django.utils import timezone

from ..facade.contracts import CallerIdentity, InvalidInput, PresetCreateInput, PresetDTO, PresetNotFound
from ..models import CloudAgentPreset, TeamCloudAgentsConfig
from .analytics import capture_event
from .config_resolution import validate_run_defaults
from .run_defaults import RUN_DEFAULT_FIELDS, run_default_columns, run_defaults_of

PRESET_UPDATE_FIELDS: Final = RUN_DEFAULT_FIELDS | {"name", "description", "tags"}


def to_preset_dto(preset: CloudAgentPreset) -> PresetDTO:
    return PresetDTO(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        tags=list(preset.tags or []),
        created_by_id=preset.created_by_id,
        created_at=preset.created_at,
        updated_at=preset.updated_at,
        **run_defaults_of(preset),
    )


def _active(team_id: int) -> QuerySet[CloudAgentPreset]:
    return CloudAgentPreset.objects.for_team(team_id).filter(deleted=False)


def _get_preset(team_id: int, preset_id: UUID) -> CloudAgentPreset:
    preset = _active(team_id).filter(id=preset_id).first()
    if preset is None:
        raise PresetNotFound()
    return preset


def _name_taken_error() -> InvalidInput:
    return InvalidInput("A preset with this name already exists. Use a different name.", attr="name")


def _validate_values(values: Mapping[str, Any], *, team_id: int, exclude_id: UUID | None = None) -> None:
    name = values.get("name")
    if "name" in values:
        if not name or not name.strip():
            raise InvalidInput("Give the preset a name.", attr="name")
        duplicates = _active(team_id).filter(name__iexact=name.strip())
        if exclude_id is not None:
            duplicates = duplicates.exclude(id=exclude_id)
        if duplicates.exists():
            raise _name_taken_error()
    validate_run_defaults(values)


def _column_values(values: Mapping[str, Any]) -> dict[str, Any]:
    columns = run_default_columns(values)
    if "name" in values:
        columns["name"] = values["name"].strip()
    if "description" in values:
        columns["description"] = values["description"]
    if "tags" in values:
        columns["tags"] = list(values["tags"] or [])
    return columns


def list_presets(team_id: int) -> list[PresetDTO]:
    return [to_preset_dto(preset) for preset in _active(team_id).order_by(Lower("name"), "id")]


def get_preset(team_id: int, preset_id: UUID) -> PresetDTO:
    return to_preset_dto(_get_preset(team_id, preset_id))


def get_preset_by_ref(team_id: int, ref: str) -> PresetDTO:
    """Find a preset by its id or, when `ref` is not an id, by its name without regard to case."""
    try:
        preset_id: UUID | None = UUID(ref)
    except ValueError:
        preset_id = None
    if preset_id is not None:
        return to_preset_dto(_get_preset(team_id, preset_id))
    preset = _active(team_id).filter(name__iexact=ref.strip()).first()
    if preset is None:
        raise PresetNotFound()
    return to_preset_dto(preset)


def create_preset(team_id: int, data: PresetCreateInput, caller: CallerIdentity) -> PresetDTO:
    # Not `dataclasses.asdict`, which would turn each repository into a dict.
    values = {field.name: getattr(data, field.name) for field in dataclasses.fields(data)}
    _validate_values(values, team_id=team_id)
    try:
        # The unique constraint decides when two requests create the same name at the same time.
        with transaction.atomic():
            preset = CloudAgentPreset.objects.for_team(team_id).create(
                team_id=team_id, created_by_id=caller.user_id, **_column_values(values)
            )
    except IntegrityError:
        raise _name_taken_error() from None
    capture_event("cloud_agents_preset_created", caller, team_id, {"preset_id": str(preset.id)})
    return to_preset_dto(preset)


def update_preset(team_id: int, preset_id: UUID, changes: Mapping[str, Any], caller: CallerIdentity) -> PresetDTO:
    """Apply `changes`, a mapping of field name to new value. A None value clears a default."""
    unknown = set(changes) - PRESET_UPDATE_FIELDS
    if unknown:
        raise InvalidInput(f"These fields cannot be changed: {', '.join(sorted(unknown))}.")
    preset = _get_preset(team_id, preset_id)
    _validate_values(changes, team_id=team_id, exclude_id=preset.id)
    columns = _column_values(changes)
    for field, value in columns.items():
        setattr(preset, field, value)
    if columns:
        try:
            with transaction.atomic():
                preset.save(update_fields=[*columns, "updated_at"])
        except IntegrityError:
            raise _name_taken_error() from None
    capture_event(
        "cloud_agents_preset_updated",
        caller,
        team_id,
        {"preset_id": str(preset.id), "changed_fields": sorted(columns)},
    )
    return to_preset_dto(preset)


def delete_preset(team_id: int, preset_id: UUID, caller: CallerIdentity) -> None:
    """Soft delete. The row stays so that runs keep their preset, and the name becomes free."""
    preset = _get_preset(team_id, preset_id)
    preset.deleted = True
    preset.deleted_at = timezone.now()
    with transaction.atomic():
        preset.save(update_fields=["deleted", "deleted_at", "updated_at"])
        # SET_NULL applies to a hard delete only, so clear the project default here.
        TeamCloudAgentsConfig.objects.for_team(team_id).filter(default_preset_id=preset.id).update(default_preset=None)
    capture_event("cloud_agents_preset_deleted", caller, team_id, {"preset_id": str(preset.id)})
