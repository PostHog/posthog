from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urljoin


def join_url(base_url: str, path: str) -> str:
    if not base_url.endswith("/"):
        base_url += "/"
    return base_url + path.lstrip("/")


def resolve_request_url(base_url: str, path: str) -> str:
    """Resolve a (possibly relative) request path against ``base_url`` — the exact URL a
    request is sent to at runtime.

    Centralized so callers that must *predict* the destination host (the custom-source
    retarget guard, its URL validator, and its credential probe) resolve it the same way
    the engine does. A literal ``http(s)://`` path is returned untouched; anything else is
    joined onto ``base_url``. The ``urljoin`` strips leading whitespace/control chars and
    normalizes the scheme before parsing, so ``" HTTPS://attacker"`` resolves to the
    attacker host here too — a string ``startswith`` check would miss it and let a
    credential be retargeted past the re-entry gate.
    """
    if path.startswith(("http://", "https://")):
        return path
    base = base_url if base_url.endswith("/") else base_url + "/"
    return urljoin(base, path.lstrip("/"))


def exclude_keys(d: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Removes specified keys from a dictionary and returns a new dictionary."""
    return {k: v for k, v in d.items() if k not in keys}
