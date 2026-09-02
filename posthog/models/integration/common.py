"""Low-level helpers shared by several provider modules (config parsing, JWT decoding)."""

import json
import base64
from collections.abc import Mapping
from typing import Any


class IntegrationError(Exception):
    """Error raised when an integration or its inputs are not valid."""

    pass


# Shared between meta.py (token refresh) and oauth.py (authorize/token-exchange URLs), which
# would otherwise import each other to read it off MetaGraphIntegration.
META_GRAPH_API_VERSION = "v25.0"


def _decode_jwt_payload(token: str) -> dict | None:
    """
    Decode JWT payload without signature verification.

    Used to extract claims from OAuth tokens (id_token, access_token) where
    we trust the token source (received directly from provider over HTTPS).

    Returns None if JWT doesn't have enough parts. Raises on decode errors
    so callers can log exceptions with full traceback.
    """
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    # Handle missing base64 padding
    decoded = base64.urlsafe_b64decode(payload + "===")
    return json.loads(decoded)


def dot_get(d: Any, path: str, default: Any = None) -> Any:
    if path in d and d[path] is not None:
        return d[path]
    for key in path.split("."):
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


ERROR_TOKEN_REFRESH_FAILED = "TOKEN_REFRESH_FAILED"


def _return_non_empty_str_from_config(
    config: Mapping,
    key: str,
    friendly_name: str,
    kind: str,
) -> str:
    if (value := config.get(key)) is not None and isinstance(value, str) and len(value) > 0:
        return value
    raise IntegrationError(f"{friendly_name} is required for {kind} integration")
