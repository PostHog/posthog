import json
from typing import TYPE_CHECKING

from django.conf import settings

import structlog
from pydantic import BaseModel, ConfigDict

from posthog.llm.gateway_client import build_openai_client
from posthog.scopes import (
    API_SCOPE_ACTIONS,
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
    PRIVILEGED_SCOPES,
)

if TYPE_CHECKING:
    from posthog.models import User

logger = structlog.get_logger(__name__)

# The experiment gating the AI scope picker. `test` gets the description box as the primary input
# with the scope list in a drawer; `control` gets today's list-first modal.
SCOPE_SUGGESTION_FEATURE_FLAG = "ai-scope-picker-experiment"
SCOPE_SUGGESTION_TEST_VARIANT = "test"

# Derived from `posthog/scopes.py` rather than listed here, so the menu the model picks from cannot
# drift from the backend's own scope list the way the frontend's hardcoded copy has.
SUGGESTABLE_SCOPE_OBJECTS: tuple[str, ...] = tuple(
    obj for obj in API_SCOPE_OBJECTS if obj not in INTERNAL_API_SCOPE_OBJECTS and obj not in OAUTH_HIDDEN_SCOPE_OBJECTS
)
SUGGESTABLE_SCOPES: frozenset[str] = (
    frozenset(f"{obj}:{action}" for obj in SUGGESTABLE_SCOPE_OBJECTS for action in API_SCOPE_ACTIONS)
    - PRIVILEGED_SCOPES
)

SYSTEM_PROMPT = """You map a description of what a PostHog API key will be used for onto the smallest \
set of API scopes that job needs.

A scope is `<object>:<action>`, where action is `read` or `write`. `write` implies `read` on the same \
object, so never return both for one object.

Rules:
- Pick only from the object list you are given. Do not invent objects, and do not return `*`.
- Return `read` unless the description implies creating, updating, or deleting that object.
- Return the minimum. A key that only reads insights does not need `dashboard:read`.
- Order the scopes most relevant first.
- If the description is too vague to map onto anything, return an empty list and say what detail \
would help.

Return ONLY a JSON object, no prose, in exactly this shape:
{"scopes": ["insight:read", "query:read"], "summary": "one sentence on why these"}
"""


def scope_suggestion_flag_person_properties(user: "User") -> dict[str, object]:
    """Person properties for evaluating the experiment flag server-side.

    The staged rollout has to run off a person property, not the `project` group: PostHog rejects a
    group-property release condition on a person-aggregated flag, and a group-aggregated one hashes
    the group key instead of the distinct id, so every member of a project would land on one variant
    and the experiment would measure nothing.

    Mirrors what the app sends via `posthog.people.set` in `userLogic`, including withholding the
    email of a user who asked to be anonymized. The frontend read picks the UI and this read guards
    the endpoint, so a condition has to resolve the same on both sides.
    """
    return {"email": user.email if not user.anonymize_data else None}


class ScopeSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scopes: list[str] = []
    summary: str = ""


def _resolve_model() -> str:
    return getattr(settings, "API_SCOPE_SUGGESTION_MODEL", "claude-haiku-4-5")


def build_user_prompt(description: str) -> str:
    objects = "\n".join(f"- {obj}" for obj in SUGGESTABLE_SCOPE_OBJECTS)
    return f"Objects you can scope to:\n{objects}\n\nWhat the key will be used for:\n{description}"


def _extract_json(content: str) -> dict:
    """Models routed through the gateway don't all honor `response_format`, so tolerate a JSON
    object wrapped in prose or a fenced block."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])


def sanitize_scopes(scopes: list[str]) -> list[str]:
    """Keep the real, user-grantable scopes in the model's order, deduped.

    `*` is dropped rather than honored: full access is the one grant a suggestion must never make on
    the user's behalf. Anything else the model invented falls out here too, so the caller can hand
    the result straight to the form.
    """
    seen: set[str] = set()
    sanitized: list[str] = []
    for raw in scopes:
        scope = raw.strip()
        if scope in seen or scope not in SUGGESTABLE_SCOPES:
            continue
        seen.add(scope)
        sanitized.append(scope)
    return sanitized


def suggest_scopes(description: str, *, distinct_id: str) -> ScopeSuggestion:
    """Ask the model which scopes a key described in free text needs. Raises on transport or parse
    failure so the caller can tell the user to fall back to picking scopes by hand."""
    client = build_openai_client(
        product="django",
        ai_product="personal-api-key-scope-suggestion",
        distinct_id=distinct_id,
    )
    completion = client.chat.completions.create(
        model=_resolve_model(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(description)},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        user=distinct_id,
    )
    suggestion = ScopeSuggestion.model_validate(_extract_json(completion.choices[0].message.content or ""))
    sanitized = sanitize_scopes(suggestion.scopes)
    logger.info(
        "scope_suggestion_generated",
        suggested_count=len(suggestion.scopes),
        kept_count=len(sanitized),
        model=_resolve_model(),
    )
    return ScopeSuggestion(scopes=sanitized, summary=suggestion.summary.strip())
