from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

from pydantic import BaseModel, Field

from posthog.models import Team, User
from posthog.models.activity_logging.utils import activity_storage
from posthog.resource_limits import LimitKey, check_count_limit

from products.actions.backend.models.action import Action, ActionStepJSON, ActionStepMatching

# Cap how many actions a single list call can return, so the tool can never blow up
# the agent's context window the way the unbounded REST default could.
MAX_LIST_LIMIT = 100
DEFAULT_LIST_LIMIT = 25

# Fields an action step accepts. Anything else passed by the LLM is dropped before
# it reaches `Action.steps`, which constructs `ActionStepJSON(**step)` and would
# otherwise raise on an unexpected key.
_STEP_FIELDS = set(ActionStepJSON.__dataclass_fields__)


class ActionStepInput(BaseModel):
    """One OR-ed trigger condition of an action. All fields optional; an empty step matches every event."""

    event: Optional[str] = Field(
        default=None, description="Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."
    )
    properties: Optional[list[dict]] = Field(
        default=None,
        description="Property filters. Each item: {'key', 'value', 'operator', 'type'} where type is 'event' or 'person'.",
    )
    selector: Optional[str] = Field(
        default=None, description="CSS selector to match the target element (e.g. 'div > button.cta')."
    )
    tag_name: Optional[str] = Field(default=None, description='HTML tag name to match (e.g. "button", "a").')
    text: Optional[str] = Field(default=None, description="Element text content to match.")
    text_matching: Optional[ActionStepMatching] = Field(default=None, description="How to match text.")
    href: Optional[str] = Field(default=None, description="Link href attribute to match.")
    href_matching: Optional[ActionStepMatching] = Field(default=None, description="How to match href.")
    url: Optional[str] = Field(default=None, description="Page URL to match.")
    url_matching: Optional[ActionStepMatching] = Field(
        default=None, description="How to match the URL (default: contains)."
    )

    def to_step_dict(self) -> dict:
        return {k: v for k, v in self.model_dump(exclude_none=True).items() if k in _STEP_FIELDS}


class ListActionsToolArgs(BaseModel):
    search: Optional[str] = Field(
        default=None,
        description="Case-insensitive substring match on the action name. Use this to find a specific action.",
    )
    limit: Optional[int] = Field(
        default=None,
        description=f"Maximum number of actions to return (1-{MAX_LIST_LIMIT}, default {DEFAULT_LIST_LIMIT}).",
    )
    offset: Optional[int] = Field(default=None, description="Number of actions to skip before returning results.")


class GetActionToolArgs(BaseModel):
    action_id: int = Field(description="ID of the action to retrieve.")


class CreateActionToolArgs(BaseModel):
    name: str = Field(description="Name of the action (must be unique within the project).")
    description: Optional[str] = Field(default=None, description="Human-readable description of the action.")
    steps: Optional[list[ActionStepInput]] = Field(
        default=None,
        description="Trigger conditions. Multiple steps are OR-ed together. Omit for an empty action you'll fill in later.",
    )


class UpdateActionToolArgs(BaseModel):
    action_id: int = Field(description="ID of the action to update.")
    name: Optional[str] = Field(default=None, description="New name. Omit to leave unchanged.")
    description: Optional[str] = Field(default=None, description="New description. Omit to leave unchanged.")
    steps: Optional[list[ActionStepInput]] = Field(
        default=None,
        description="Replacement trigger conditions. When provided, REPLACES all existing steps. Omit to leave steps unchanged.",
    )


class DeleteActionToolArgs(BaseModel):
    action_id: int = Field(description="ID of the action to delete.")


class ActionToolError(ValueError):
    """Raised for user-fixable problems (not found, duplicate name, invalid step). Surfaced as a retryable error."""


@contextmanager
def _acting_user(user: User) -> Iterator[None]:
    """Attribute activity-log entries from a direct ORM save to `user` (no request middleware here)."""
    previous = activity_storage.get_user()
    activity_storage.set_user(user)
    try:
        yield
    finally:
        activity_storage.set_user(previous)


def _format_step(step: ActionStepJSON) -> str:
    parts: list[str] = []
    if step.event is not None:
        parts.append(f"event={step.event}")
    if step.url:
        parts.append(f"url {step.url_matching or 'contains'} {step.url!r}")
    if step.selector:
        parts.append(f"selector={step.selector!r}")
    if step.tag_name:
        parts.append(f"tag={step.tag_name}")
    if step.text:
        parts.append(f"text {step.text_matching or 'exact'} {step.text!r}")
    if step.href:
        parts.append(f"href {step.href_matching or 'exact'} {step.href!r}")
    if step.properties:
        parts.append(f"{len(step.properties)} property filter(s)")
    return ", ".join(parts) or "matches all events"


def _format_action(action: Action, *, detailed: bool = False) -> str:
    lines = [f"#{action.id} {action.name or '(unnamed)'}"]
    if action.description:
        lines.append(f"  description: {action.description}")
    steps = action.steps
    if steps:
        if detailed:
            for i, step in enumerate(steps, 1):
                lines.append(f"  step {i}: {_format_step(step)}")
        else:
            lines.append(f"  steps: {len(steps)} ({'; '.join(_format_step(s) for s in steps)})")
    else:
        lines.append("  steps: none")
    if action.bytecode_error:
        lines.append(f"  ⚠ bytecode error: {action.bytecode_error}")
    return "\n".join(lines)


def list_actions(team: Team, search: Optional[str], limit: Optional[int], offset: Optional[int]) -> str:
    qs = Action.objects.filter(team=team, deleted=False)
    if search:
        qs = qs.filter(name__icontains=search)
    total = qs.count()
    qs = qs.order_by("name")
    start = offset or 0
    capped_limit = min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)
    actions = list(qs[start : start + capped_limit])

    if not actions:
        if total == 0:
            return "No actions found matching the filter."
        return f"No actions at offset {start} (project has {total} matching the filter) — try a lower offset."

    header = f"Showing {len(actions)} of {total} action(s)"
    if start:
        header += f", starting at offset {start}"
    body = "\n".join(_format_action(a) for a in actions)
    footer = ""
    if start + len(actions) < total:
        footer = (
            f"\n\n{total - start - len(actions)} more — increase offset to {start + len(actions)} for the next page."
        )
    return f"{header}:\n{body}{footer}"


def get_action_object(team: Team, action_id: int) -> Action:
    try:
        return Action.objects.get(team=team, pk=action_id, deleted=False)
    except Action.DoesNotExist:
        raise ActionToolError(f"No action with ID {action_id} exists in this project.")


def format_action_detail(action: Action) -> str:
    """Detailed, human-readable rendering of a single (already-fetched) action for tool output."""
    return _format_action(action, detailed=True)


def _check_name_available(team_id: int, name: str, *, exclude_id: Optional[int] = None) -> None:
    if not name.strip():
        raise ActionToolError("Action name may not be blank.")
    clash = Action.objects.filter(team_id=team_id, name=name, deleted=False)
    if exclude_id is not None:
        clash = clash.exclude(pk=exclude_id)
    existing_id = clash.values_list("id", flat=True).first()
    if existing_id:
        raise ActionToolError(f"This project already has an action named {name!r} (ID {existing_id}).")


def create_action(
    team: Team, user: User, name: str, description: Optional[str], steps: Optional[list[ActionStepInput]]
) -> str:
    _check_name_available(team.id, name)
    # Emit the same "resource limit hit" telemetry the REST create path does. This is
    # notification-only — check_count_limit never raises or blocks.
    current_count = Action.objects.filter(team=team, deleted=False).count()
    check_count_limit(team=team, key=LimitKey.MAX_ACTIONS_PER_TEAM, current_count=current_count, user=user)
    action = Action(team=team, name=name, description=description or "", created_by=user)
    if steps:
        action.steps = [s.to_step_dict() for s in steps]
    with _acting_user(user):
        action.save()
    return f"Created action:\n{_format_action(action, detailed=True)}"


def update_action(
    user: User,
    action: Action,
    name: Optional[str],
    description: Optional[str],
    steps: Optional[list[ActionStepInput]],
) -> str:
    if name is None and description is None and steps is None:
        return f"Nothing to update — action #{action.id} left unchanged:\n{_format_action(action, detailed=True)}"
    if name is not None:
        _check_name_available(action.team_id, name, exclude_id=action.pk)
        action.name = name
    if description is not None:
        action.description = description
    if steps is not None:
        action.steps = [s.to_step_dict() for s in steps]
    with _acting_user(user):
        action.save()
    return f"Updated action:\n{_format_action(action, detailed=True)}"


def delete_action(user: User, action: Action) -> str:
    action.deleted = True
    with _acting_user(user):
        action.save()
    return f"Deleted action #{action.id} {action.name or '(unnamed)'}."
