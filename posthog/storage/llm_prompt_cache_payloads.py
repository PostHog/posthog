from datetime import datetime
from typing import Any

from posthog.models.llm_prompt import LLMPrompt

INTERNAL_FIRST_VERSION_ID_KEY = "_first_version_id"


def _serialize_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def serialize_prompt(prompt: LLMPrompt, *, include_internal: bool = False) -> dict[str, Any]:
    first_version_created_at = getattr(prompt, "first_version_created_at", prompt.created_at) or prompt.created_at
    if isinstance(first_version_created_at, datetime):
        first_version_created_at = _serialize_timestamp(first_version_created_at)

    first_version_id = getattr(prompt, "first_version_id", None)
    serialized_first_version_id = str(first_version_id) if first_version_id is not None else None
    if serialized_first_version_id is None and prompt.version == 1:
        serialized_first_version_id = str(prompt.id)

    serialized_prompt = {
        "id": str(prompt.id),
        "name": prompt.name,
        "prompt": prompt.prompt,
        "version": prompt.version,
        "created_at": _serialize_timestamp(prompt.created_at),
        "updated_at": _serialize_timestamp(prompt.updated_at),
        "deleted": prompt.deleted,
        "is_latest": bool(getattr(prompt, "is_latest", False)),
        "latest_version": int(getattr(prompt, "latest_version", prompt.version)),
        "version_count": int(getattr(prompt, "version_count", 1)),
        "first_version_created_at": first_version_created_at,
    }
    if include_internal and serialized_first_version_id is not None:
        serialized_prompt[INTERNAL_FIRST_VERSION_ID_KEY] = serialized_first_version_id
    return serialized_prompt


def serialize_prompt_version(prompt: LLMPrompt, *, include_internal: bool = False) -> dict[str, Any]:
    serialized_prompt = {
        "id": str(prompt.id),
        "name": prompt.name,
        "prompt": prompt.prompt,
        "version": prompt.version,
        "created_at": _serialize_timestamp(prompt.created_at),
        "updated_at": _serialize_timestamp(prompt.updated_at),
        "deleted": prompt.deleted,
    }
    if include_internal:
        first_version_id = getattr(prompt, "first_version_id", None)
        if first_version_id is not None:
            serialized_prompt[INTERNAL_FIRST_VERSION_ID_KEY] = str(first_version_id)
        elif prompt.version == 1:
            serialized_prompt[INTERNAL_FIRST_VERSION_ID_KEY] = str(prompt.id)
    return serialized_prompt


def merge_prompt_version_history_metadata(
    prompt_version: dict[str, Any], latest_prompt: dict[str, Any]
) -> dict[str, Any]:
    merged_prompt = {
        **prompt_version,
        "deleted": False,
        "is_latest": prompt_version["version"] == latest_prompt["latest_version"],
        "latest_version": latest_prompt["latest_version"],
        "version_count": latest_prompt["version_count"],
        "first_version_created_at": latest_prompt["first_version_created_at"],
    }
    generation_marker = latest_prompt.get(INTERNAL_FIRST_VERSION_ID_KEY)
    if isinstance(generation_marker, str):
        merged_prompt[INTERNAL_FIRST_VERSION_ID_KEY] = generation_marker
    return merged_prompt


def strip_internal_metadata(prompt: dict[str, Any]) -> dict[str, Any]:
    public_prompt = dict(prompt)
    public_prompt.pop(INTERNAL_FIRST_VERSION_ID_KEY, None)
    return public_prompt


def is_stale_exact_version_entry(exact_prompt: dict[str, Any], latest_prompt: dict[str, Any]) -> bool:
    exact_first_version_id = exact_prompt.get(INTERNAL_FIRST_VERSION_ID_KEY)
    latest_first_version_id = latest_prompt.get(INTERNAL_FIRST_VERSION_ID_KEY)
    if not isinstance(exact_first_version_id, str) or not isinstance(latest_first_version_id, str):
        return True
    return exact_first_version_id != latest_first_version_id
