import json
from typing import Any

MAX_PROMPT_PAYLOAD_BYTES = 1_000_000


def normalize_prompt_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return ""
