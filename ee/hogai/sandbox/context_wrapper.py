"""Pure helpers for wrapping a sandbox user message with a ``<posthog_context>`` block.

The wrapper renders the user's attached PostHog entity references (and free text) into a
deterministic Markdown-ish block that gets prepended to the user message before it reaches the
cloud-agent. The template lives only here, in Python — the frontend never builds it (see
``docs/internal/posthog-ai-migration/01_CONTEXT.md`` § 4.3). Both functions are pure and
side-effect-free so they are trivially snapshot-testable.
"""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

# The 8 attachment types the sandbox runtime accepts. Seven entity types plus free text.
AttachedContextType = Literal[
    "dashboard",
    "insight",
    "event",
    "action",
    "error_tracking_issue",
    "evaluation",
    "notebook",
    "text",
]

ENTITY_CONTEXT_TYPES: frozenset[str] = frozenset(
    {
        "dashboard",
        "insight",
        "event",
        "action",
        "error_tracking_issue",
        "evaluation",
        "notebook",
    }
)

# Human-readable label per entity type, used in the rendered block.
_ENTITY_LABELS: dict[str, str] = {
    "dashboard": "Dashboard",
    "insight": "Insight",
    "event": "Event",
    "action": "Action",
    "error_tracking_issue": "Error tracking issue",
    "evaluation": "Evaluation",
    "notebook": "Notebook",
}

_CONTEXT_HEADER = (
    "The user attached the following PostHog entities. "
    "Use the appropriate tools to retrieve their details only if relevant to the request."
)


class AttachedContext(BaseModel):
    """A single typed attachment carried by a sandbox user message.

    ``id``/``name`` apply to entity types; ``value`` carries the text for ``type == "text"``.
    """

    type: AttachedContextType
    id: str | int | None = None
    name: str | None = None
    value: str | None = None


def wrap_user_message(content: str, attached_context: list[AttachedContext]) -> str:
    """Prepend a rendered ``<posthog_context>`` block to ``content``.

    Returns ``content`` unchanged when there is nothing to attach, so an empty list (or a list
    that dedupe reduced to empty) forwards the user's message without any wrapper noise.
    """
    if not attached_context:
        return content
    block = _render_posthog_context_block(attached_context)
    return f"{block}\n\n{content}"


def prune_repeated_entity_refs(
    attached: list[AttachedContext],
    prior: Iterable[tuple[str, str | int]],
) -> list[AttachedContext]:
    """Drop entity refs ``(type, id)`` already named in earlier messages of the same conversation.

    ``text`` items are NEVER deduped — repeated text is intentional (e.g. consecutive error
    snippets). The agent retains entity IDs from prior turns, so re-listing them inflates the
    prompt without adding information; it can re-fetch any prior entity via its read tools.
    """
    seen: set[tuple[str, str | int]] = set(prior)
    out: list[AttachedContext] = []
    for item in attached:
        if item.type == "text":
            out.append(item)
            continue
        if item.id is None:
            # An entity ref with no id can't be deduped on identity; keep it.
            out.append(item)
            continue
        key = (item.type, item.id)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _render_posthog_context_block(items: list[AttachedContext]) -> str:
    lines = ["<posthog_context>", _CONTEXT_HEADER]
    for item in items:
        lines.append(_format_item(item))
    lines.append("</posthog_context>")
    return "\n".join(lines)


def _format_item(item: AttachedContext) -> str:
    """Render one attachment line.

    Free text becomes ``- Free text: "…"``; entities become ``- <Label> #<id> ("<name>")`` with
    the name omitted when absent. Does not name specific tool function signatures (that lives in
    the tool descriptions) — only the entity type, id, and optional label.
    """
    if item.type == "text":
        return f'- Free text: "{item.value or ""}"'

    label = _ENTITY_LABELS.get(item.type, item.type)
    id_part = f" #{item.id}" if item.id is not None else ""
    name_part = f' ("{item.name}")' if item.name else ""
    return f"- {label}{id_part}{name_part}"
