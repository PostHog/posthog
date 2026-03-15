from __future__ import annotations

import json
from typing import Any

MAX_TEXT_LENGTH = 2000
MAX_ERROR_LENGTH = 500


def truncate_text(value: str | None, *, max_length: int = MAX_TEXT_LENGTH) -> str | None:
    if value is None:
        return None
    if len(value) <= max_length:
        return value
    return f"{value[:max_length]}...[truncated {len(value) - max_length} chars]"


def without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if hasattr(value, "dict"):
        return value.dict(exclude_none=True)
    return str(value)


def serialize_value(value: Any, *, max_length: int = MAX_TEXT_LENGTH) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return truncate_text(value, max_length=max_length)
    try:
        serialized = json.dumps(value, default=_json_default, ensure_ascii=True, sort_keys=True)
    except TypeError:
        serialized = str(value)
    return truncate_text(serialized, max_length=max_length)


def render_prompt_template(template: str, *, input_text: str, output_text: str, expected_text: str) -> str:
    replacements = {
        "{{input}}": input_text,
        "{{output}}": output_text,
        "{{expected}}": expected_text,
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def parse_json_object(text: str | None) -> dict[str, Any]:
    if not text:
        raise ValueError("Judge returned empty output")

    trimmed = text.strip()
    candidates = [trimmed]
    fenced_match = trimmed.startswith("```") and trimmed.endswith("```")
    if fenced_match:
        lines = trimmed.splitlines()
        candidates.append("\n".join(lines[1:-1]).strip())

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"Judge output was not valid JSON: {trimmed}")
