"""
Contract types for actions.

Frozen dataclasses and errors that cross the actions boundary. No Django imports.

These use the stdlib dataclass, not the pydantic one: an action's steps come from a JSON column
that older code wrote, and the HogQL compiler has always read those rows as they are. Validating
them on the way out would turn a stored step that compiles today into a read that fails.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal, Optional, get_args

ActionStepMatching = Literal["contains", "regex", "exact"]
ACTION_STEP_MATCHING_OPTIONS: tuple[ActionStepMatching, ...] = get_args(ActionStepMatching)


class ActionNotFound(Exception):
    """No action with that id exists in the requested scope."""


@dataclasses.dataclass(frozen=True)
class ActionStep:
    """One way an event can match an action. The steps of an action are OR-ed together.

    The field names and defaults are the stored step shape, so `ActionStep(**stored_step)` reads a
    stored step and `dataclasses.asdict(step)` writes one.
    """

    tag_name: Optional[str] = None
    text: Optional[str] = None
    text_matching: Optional[ActionStepMatching] = None
    href: Optional[str] = None
    href_matching: Optional[ActionStepMatching] = None
    selector: Optional[str] = None
    url: Optional[str] = None
    url_matching: Optional[ActionStepMatching] = "contains"
    event: Optional[str] = None
    properties: Optional[list[dict]] = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Action:
    id: int
    team_id: int
    name: Optional[str]
    description: str
    steps: tuple[ActionStep, ...]
    deleted: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    pinned_at: Optional[datetime]
    last_calculated_at: Optional[datetime]
    summary: Optional[str]

    def get_step_events(self) -> list[Optional[str]]:
        """The event each step matches, in step order. A step that matches any event gives None."""
        return [step.event for step in self.steps]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionCatalogEntry:
    """An action as a picker lists it: no steps, and the description cut to `short_description`."""

    id: int
    name: Optional[str]
    short_description: Optional[str]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionRecentEntry:
    id: int
    name: Optional[str]
    updated_at: Optional[datetime]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionInventory:
    """How many live actions a team has, and the ones changed most recently."""

    total_count: int
    recent: tuple[ActionRecentEntry, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionEmbeddingSource:
    """An action whose summary still has to reach the vector store."""

    id: int
    team_id: int
    name: Optional[str]
    description: str
    summary: Optional[str]
    deleted: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionBytecode:
    """What the last save compiled an action's steps to. `bytecode` is None when compiling failed."""

    bytecode: Optional[list]
    bytecode_error: Optional[str]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionAiState:
    """Where an action stands in the AI summary and embedding sync."""

    summary: Optional[str]
    last_summarized_at: Optional[datetime]
    embedding_last_synced_at: Optional[datetime]
    embedding_version: Optional[int]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionSaved:
    """An action row was written. Handlers registered with `on_action_saved` receive this."""

    action_id: int
    team_id: int
    created: bool


def steps_from_json(steps_json: Optional[Sequence[Mapping]]) -> tuple[ActionStep, ...]:
    """Steps in the stored JSON shape, as contracts. An unknown key raises `TypeError`, as it always has."""
    return tuple(ActionStep(**step) for step in steps_json or [])
