from collections.abc import Iterable, Mapping
from typing import Any


def join_url(base_url: str, path: str) -> str:
    if not base_url.endswith("/"):
        base_url += "/"
    return base_url + path.lstrip("/")


def exclude_keys(d: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Removes specified keys from a dictionary and returns a new dictionary."""
    return {k: v for k, v in d.items() if k not in keys}
