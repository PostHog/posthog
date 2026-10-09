"""Merge the settings of one call, its preset and the project into the configuration a run uses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from posthog.dataclasses import frozen

from products.tasks.backend.facade.cloud_agents import (
    MAX_INACTIVITY_TIMEOUT_SECONDS,
    CloudAgentTaskInvalid,
    validate_cloud_agent_output_schema,
)

from ..facade.contracts import (
    InvalidInput,
    PresetDTO,
    RepositoryRef,
    RepositoryRequired,
    ResolvedRunConfig,
    RunCreateInput,
    TeamSettingsDTO,
)
from ..facade.enums import InferenceMode, SizeName

MIN_IDLE_MINUTES: Final = 1
# Tasks clamps a longer time to this limit, so a longer value would not do what it says.
MAX_IDLE_MINUTES: Final = MAX_INACTIVITY_TIMEOUT_SECONDS // 60
MAX_REPOSITORIES: Final = 1


@frozen
class ProductDefaults:
    size: SizeName = SizeName.S_4X16
    inference: InferenceMode = InferenceMode.AUTO
    create_pr: bool = True
    idle_minutes: int = 10
    # The run step selects a model when no level sets one.
    model: str | None = None


PRODUCT_DEFAULTS: Final = ProductDefaults()


def _first_set(field: str, *sources: object | None) -> Any:
    for source in sources:
        value = getattr(source, field, None) if source is not None else None
        if value is not None:
            return value
    return None


def _first_repositories(*sources: object | None) -> list[RepositoryRef]:
    """The list of the first level that names a repository. An empty list names none."""
    for source in sources:
        repositories = getattr(source, "repositories", None) if source is not None else None
        if repositories:
            return list(repositories)
    return []


def _merge_tags(*tag_lists: list[str] | None) -> list[str]:
    merged: dict[str, None] = {}
    for tags in tag_lists:
        for tag in tags or []:
            merged.setdefault(tag)
    return list(merged)


def _join_instructions(*blocks: str | None) -> str | None:
    kept = [block.strip() for block in blocks if block and block.strip()]
    return "\n\n".join(kept) if kept else None


def validate_repositories(repositories: Sequence[RepositoryRef]) -> None:
    if len(repositories) > MAX_REPOSITORIES:
        raise InvalidInput("Only one repository is supported for now.", attr="repositories")


def validate_idle_minutes(value: int) -> None:
    if not MIN_IDLE_MINUTES <= value <= MAX_IDLE_MINUTES:
        raise InvalidInput(
            f"The idle time must be from {MIN_IDLE_MINUTES} to {MAX_IDLE_MINUTES} minutes.", attr="idle_minutes"
        )


def validate_output_schema(schema: Mapping[str, Any]) -> None:
    try:
        validate_cloud_agent_output_schema(schema)
    except CloudAgentTaskInvalid as error:
        raise InvalidInput(error.detail, attr="output_schema") from None


def validate_run_defaults(values: Mapping[str, Any]) -> None:
    """Check the run defaults in `values`, a mapping of field name to value. A None value sets no default."""
    if values.get("repositories") is not None:
        validate_repositories(values["repositories"])
    if values.get("idle_minutes") is not None:
        validate_idle_minutes(values["idle_minutes"])
    if values.get("output_schema") is not None:
        validate_output_schema(values["output_schema"])


def resolve_run_config(call: RunCreateInput, preset: PresetDTO | None, team: TeamSettingsDTO) -> ResolvedRunConfig:
    """Take each field from the first level that sets it: call, preset, project, product default."""
    repositories = _first_repositories(call, preset, team)
    if not repositories:
        raise RepositoryRequired()
    validate_repositories(repositories)

    idle_minutes = _first_set("idle_minutes", call, preset, team, PRODUCT_DEFAULTS)
    validate_idle_minutes(idle_minutes)
    output_schema = _first_set("output_schema", call, preset, team)
    if output_schema is not None:
        validate_output_schema(output_schema)

    return ResolvedRunConfig(
        repositories=repositories,
        model=_first_set("model", call, preset, team, PRODUCT_DEFAULTS),
        reasoning_effort=_first_set("reasoning_effort", call, preset, team),
        size=SizeName(_first_set("size", call, preset, team, PRODUCT_DEFAULTS)),
        inference=InferenceMode(_first_set("inference", call, preset, team, PRODUCT_DEFAULTS)),
        # Broad guidance comes first, so the more specific level has the last word.
        instructions=_join_instructions(team.instructions, preset.instructions if preset else None, call.instructions),
        create_pr=_first_set("create_pr", call, preset, team, PRODUCT_DEFAULTS),
        idle_minutes=idle_minutes,
        output_schema=output_schema,
        tags=_merge_tags(preset.tags if preset else None, call.tags),
        preset_id=preset.id if preset else None,
    )


def render_prompt(config: ResolvedRunConfig, prompt: str) -> str:
    """Put the instructions block above the prompt. Without instructions, return the prompt unchanged."""
    if not config.instructions:
        return prompt
    return f"<instructions>\n{config.instructions}\n</instructions>\n\n{prompt}"
