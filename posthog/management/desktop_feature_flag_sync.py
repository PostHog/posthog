import json
from pathlib import Path
from typing import cast

from django.core.management.base import CommandError

DESKTOP_FEATURE_FLAG_KEYS_PATH = (
    Path(__file__).resolve().parents[2]
    / "products"
    / "desktop"
    / "packages"
    / "shared"
    / "src"
    / "feature-flag-keys.json"
)

DESKTOP_MULTIVARIATE_FLAGS = {"bedrock-llm-gateway": ["test", "control"]}


def load_desktop_feature_flags() -> dict[str, str | list[str]]:
    raw: object = json.loads(DESKTOP_FEATURE_FLAG_KEYS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CommandError("Desktop feature flag keys must be a JSON object.")

    flag_keys = cast(dict[object, object], raw)
    if not all(isinstance(name, str) and isinstance(key, str) for name, key in flag_keys.items()):
        raise CommandError("Desktop feature flag names and keys must be strings.")

    keys = cast(dict[str, str], flag_keys).values()
    return {key: DESKTOP_MULTIVARIATE_FLAGS.get(key, "boolean") for key in keys}
