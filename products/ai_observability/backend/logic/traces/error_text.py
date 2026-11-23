import json
from typing import Any

ERROR_TEXT_MAX_CHARS = 200


def parse_json(raw: Any) -> Any:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def is_truthy_json(raw: Any) -> bool:
    return bool(parse_json(raw))


def error_text(raw_json: str | None) -> str | None:
    value = parse_json(raw_json)
    if not value:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:ERROR_TEXT_MAX_CHARS]
