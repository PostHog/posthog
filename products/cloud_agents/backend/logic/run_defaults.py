"""Read and write the run defaults that a preset row and the project settings row both hold."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Final

from ..facade.contracts import RepositoryRef
from ..facade.enums import CloudAgentReasoningEffort, InferenceMode, SizeName
from ..models import RunDefaultsMixin

RUN_DEFAULT_FIELDS: Final = frozenset(
    {
        "repositories",
        "model",
        "reasoning_effort",
        "size",
        "inference",
        "instructions",
        "create_pr",
        "idle_minutes",
        "output_schema",
    }
)


def run_defaults_of(row: RunDefaultsMixin) -> dict[str, Any]:
    """The run defaults of a row, as the keyword arguments that `PresetDTO` and `TeamSettingsDTO` share."""
    return {
        "repositories": (
            [RepositoryRef.from_json(repository) for repository in row.repositories] if row.repositories else None
        ),
        "model": row.model,
        "reasoning_effort": CloudAgentReasoningEffort(row.reasoning_effort) if row.reasoning_effort else None,
        "size": SizeName(row.size) if row.size else None,
        "inference": InferenceMode(row.inference) if row.inference else None,
        "instructions": row.instructions,
        "create_pr": row.create_pr,
        "idle_minutes": row.idle_minutes,
        "output_schema": row.output_schema,
    }


def run_default_columns(values: Mapping[str, Any]) -> dict[str, Any]:
    """The column values for the run defaults in `values`. Other keys of `values` are left out."""
    columns: dict[str, Any] = {}
    for field in RUN_DEFAULT_FIELDS & set(values):
        value = values[field]
        if field == "repositories":
            # An empty list names no repository, the same as no default.
            columns[field] = [repository.to_json() for repository in value] if value else None
        elif isinstance(value, Enum):
            columns[field] = value.value
        else:
            columns[field] = value
    return columns
