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
from enum import StrEnum
from typing import Any, Literal, Optional, get_args
from uuid import UUID

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
class ActionCreator:
    """The user fields the API shows for a creator, the ones core's `UserBasicSerializer` renders."""

    id: int
    uuid: UUID
    distinct_id: Optional[str]
    first_name: str
    last_name: str
    email: str
    is_email_verified: Optional[bool]
    hedgehog_config: Optional[dict[str, Any]]
    role_at_organization: Optional[str]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionDetail:
    """An action with everything the actions API shows for it."""

    id: int
    team_id: int
    name: Optional[str]
    description: str
    tags: tuple[str, ...]
    post_to_slack: bool
    slack_message_format: str
    steps: tuple[ActionStep, ...]
    created_at: datetime
    created_by_id: Optional[int]
    created_by: Optional[ActionCreator]
    deleted: bool
    last_calculated_at: Optional[datetime]
    bytecode_error: Optional[str]
    pinned_at: Optional[datetime]

    def get_step_events(self) -> list[Optional[str]]:
        """The event each step matches, in step order. A step that matches any event gives None."""
        return [step.event for step in self.steps]


ActionOrderingField = Literal["name", "created_at", "pinned_at", "created_by"]
ACTION_ORDERING_FIELDS: tuple[ActionOrderingField, ...] = get_args(ActionOrderingField)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionOrdering:
    """A sort the actions list can apply. `created_by` sorts by the creator's name, not by the user id."""

    field: ActionOrderingField
    descending: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionListFilters:
    """Narrows the actions list. A filter left empty does not filter."""

    # Case-insensitive substring of the name.
    search: Optional[str] = None
    created_by_ids: tuple[int, ...] = ()
    # An action matches when it has any of these tags.
    tags: tuple[str, ...] = ()
    # Without an ordering, the list sorts by the last calculation time, newest first, and then by name.
    ordering: Optional[ActionOrdering] = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionListAccess:
    """Which actions the access control rules let a list show the viewer.

    With `only_allowed`, the viewer has no resource-level access: the list keeps the allowed ids and the
    viewer's own actions. Otherwise it drops the blocked ids, except the viewer's own actions.
    """

    viewer_id: int
    only_allowed: bool
    allowed_ids: frozenset[str]
    blocked_ids: frozenset[str]


class ActionWriteField(StrEnum):
    NAME = "name"
    DESCRIPTION = "description"
    POST_TO_SLACK = "post_to_slack"
    SLACK_MESSAGE_FORMAT = "slack_message_format"
    STEPS = "steps"
    DELETED = "deleted"
    LAST_CALCULATED_AT = "last_calculated_at"
    PINNED_AT = "pinned_at"
    TAGS = "tags"
    CREATE_IN_FOLDER = "create_in_folder"


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionWrite:
    """The fields a create or an update sets.

    Only the fields named in `fields_set` are written. On a create the others take the model defaults; on an
    update they keep the stored values. Tags named here replace the action's tags.
    """

    fields_set: frozenset[ActionWriteField]
    name: Optional[str] = None
    description: str = ""
    post_to_slack: bool = False
    slack_message_format: str = ""
    steps: tuple[ActionStep, ...] = ()
    deleted: bool = False
    last_calculated_at: Optional[datetime] = None
    # A create stores the value. An update ignores the value: a datetime pins the action at the time of the
    # write, or keeps the stored time when the action is already pinned, and None unpins it.
    pinned_at: Optional[datetime] = None
    tags: tuple[str, ...] = ()
    # The file system folder the action is filed in. An empty string files it at the root.
    create_in_folder: Optional[str] = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionAnalytics:
    """What the `action created` and `action updated` analytics events report about an action."""

    post_to_slack: bool
    name_length: int
    custom_slack_message_format: bool
    # The legacy precalculated event matches, which nothing writes anymore.
    event_count_precalc: int
    step_count: int
    match_text_count: int
    match_href_count: int
    match_selector_count: int
    match_url_count: int
    has_properties: bool
    deleted: bool
    pinned: bool
    pinned_at: Optional[datetime]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionWriteResult:
    action: ActionDetail
    analytics: ActionAnalytics


ActionReferenceType = Literal["insight", "experiment", "cohort", "hog_function"]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionReference:
    """A resource of another product that uses an action."""

    type: ActionReferenceType
    # An integer, a UUID or an insight short id, depending on the type.
    id: str
    name: str
    url: str
    created_at: Optional[datetime]
    created_by: Optional[ActionCreator]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActionTagChange:
    """The tags an action has after a bulk tag change."""

    id: int
    tags: tuple[str, ...]


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
