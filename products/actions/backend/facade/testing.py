"""Test-support facade for actions.

Suites outside this product plant, edit and remove actions through here instead of importing the
model. Each helper goes through the model's save, so an action written here compiles its bytecode
and fires the same save hooks as one written through the API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async

from products.actions.backend.facade import contracts
from products.actions.backend.facade.api import _to_contract
from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    from posthog.models import Team, User

__all__ = [
    "acreate_action",
    "aget_action_ai_state",
    "create_action",
    "delete_action",
    "get_action_ai_state",
    "get_action_bytecode",
    "update_action",
]

_UNSET = object()


def create_action(
    *,
    id: int | None = None,
    team: Team | None = None,
    team_id: int | None = None,
    name: str | None = None,
    steps_json: Sequence[Mapping[str, object]] | None = None,
    description: str = "",
    created_by: User | None = None,
    deleted: bool = False,
    pinned_at: datetime | str | None = None,
    last_calculated_at: datetime | str | None = None,
    summary: str | None = None,
    last_summarized_at: datetime | str | None = None,
    embedding_last_synced_at: datetime | str | None = None,
    embedding_version: int | None = None,
    post_to_slack: bool = False,
    slack_message_format: str = "",
) -> contracts.Action:
    """Create an action with its steps in the stored JSON shape, and return it.

    Give the team as `team` or as `team_id`. Fields left as None take the model defaults; a timestamp may be an
    ISO string, as the model accepts. `id` pins the
    primary key, for a fixture that a stored payload names by a fixed id.
    """
    if (team is None) == (team_id is None):
        raise ValueError("Pass exactly one of team and team_id")
    optional_fields = {
        "id": id,
        "pinned_at": pinned_at,
        "last_calculated_at": last_calculated_at,
        "summary": summary,
        "last_summarized_at": last_summarized_at,
        "embedding_last_synced_at": embedding_last_synced_at,
        "embedding_version": embedding_version,
    }
    action = Action.objects.create(
        **({"team": team} if team is not None else {"team_id": team_id}),
        name=name,
        steps_json=[dict(step) for step in steps_json] if steps_json is not None else None,
        description=description,
        created_by=created_by,
        deleted=deleted,
        post_to_slack=post_to_slack,
        slack_message_format=slack_message_format,
        **{field: value for field, value in optional_fields.items() if value is not None},
    )
    return _to_contract(action)


acreate_action = sync_to_async(create_action)


def update_action(
    action: contracts.Action,
    *,
    name: object = _UNSET,
    description: object = _UNSET,
    steps_json: object = _UNSET,
    deleted: object = _UNSET,
    pinned_at: object = _UNSET,
    last_calculated_at: object = _UNSET,
    summary: object = _UNSET,
    last_summarized_at: object = _UNSET,
    updated_at: object = _UNSET,
    embedding_last_synced_at: object = _UNSET,
    embedding_version: object = _UNSET,
) -> contracts.Action:
    """Change the given fields and save, as an edit through the API would. Returns the saved action.

    `updated_at` is stamped by every save, so a backdated one is written with a separate update.
    """
    row = Action.objects.get(team_id=action.team_id, pk=action.id)
    fields = {
        "name": name,
        "description": description,
        "steps_json": steps_json,
        "deleted": deleted,
        "pinned_at": pinned_at,
        "last_calculated_at": last_calculated_at,
        "summary": summary,
        "last_summarized_at": last_summarized_at,
        "embedding_last_synced_at": embedding_last_synced_at,
        "embedding_version": embedding_version,
    }
    for field, value in fields.items():
        if value is not _UNSET:
            setattr(row, field, value)
    row.save()
    if updated_at is not _UNSET:
        Action.objects.filter(team_id=action.team_id, pk=action.id).update(updated_at=updated_at)
        row.refresh_from_db()
    return _to_contract(row)


def delete_action(action: contracts.Action) -> None:
    """Remove the action row, as a team deletion does. The API only ever soft-deletes."""
    Action.objects.get(team_id=action.team_id, pk=action.id).delete()


def get_action_bytecode(action: contracts.Action) -> contracts.ActionBytecode:
    """The bytecode the last save compiled for the action, or the error it hit."""
    bytecode, bytecode_error = Action.objects.values_list("bytecode", "bytecode_error").get(
        team_id=action.team_id, pk=action.id
    )
    return contracts.ActionBytecode(bytecode=bytecode, bytecode_error=bytecode_error)


def get_action_ai_state(action: contracts.Action) -> contracts.ActionAiState:
    """Where the action stands in the AI summary and embedding sync."""
    summary, last_summarized_at, embedding_last_synced_at, embedding_version = Action.objects.values_list(
        "summary", "last_summarized_at", "embedding_last_synced_at", "embedding_version"
    ).get(team_id=action.team_id, pk=action.id)
    return contracts.ActionAiState(
        summary=summary,
        last_summarized_at=last_summarized_at,
        embedding_last_synced_at=embedding_last_synced_at,
        embedding_version=embedding_version,
    )


aget_action_ai_state = sync_to_async(get_action_ai_state)
