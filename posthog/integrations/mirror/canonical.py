"""JavaScript-compatible canonical JSON and the salted content digest of an integration row.

Must give the same bytes as `canonicalJson` and `contentDigest` in the credentials service
(`services/credentials-service/src/integrations/digest.ts`). The shared vectors in
`services/credentials-service/tests/fixtures/content-digest-vectors.json` pin both sides.

The output follows RFC 8785 (JCS) with two exceptions:
- A lone surrogate is escaped as `\\udxxx`, as JSON.stringify does. RFC 8785 rejects it.
- An integer that an IEEE double cannot hold exactly raises ValueError. JavaScript would round it,
  and the digest would then hide a changed value.
"""

import re
import hmac
import math
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import field
from decimal import Decimal
from typing import Any

from posthog.dataclasses import frozen

CONTENT_DIGEST_VERSION = 1

_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# What JSON.stringify escapes: quote, backslash, C0 controls and lone surrogates.
_NEEDS_ESCAPE = re.compile('["\\\\\x00-\x1f\ud800-\udfff]')


@frozen
class DigestParts:
    config: Mapping[str, Any]
    errors: str
    external_id: str | None
    sensitive_config: Mapping[str, Any] = field(repr=False)
    unreadable_keys: Sequence[str]


def canonical_json(value: Any) -> str:
    """JSON with keys sorted by UTF-16 code units and no whitespace, byte-equal to JSON.stringify output.

    Raises ValueError for a value JSON cannot carry exactly.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        items: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"canonical JSON object keys must be strings, not {type(key).__name__}")
            js_key = _as_js_string(key)
            if js_key in items:
                raise ValueError("canonical JSON object has two keys with the same UTF-16 code units")
            items[js_key] = item
        return "{" + ",".join(f"{_string(key)}:{canonical_json(items[key])}" for key in _utf16_sorted(items)) + "}"
    raise ValueError(f"canonical JSON cannot encode a value of type {type(value).__name__}")


def content_digest(salt: bytes, parts: DigestParts) -> str:
    """Lowercase hex HMAC-SHA256, keyed by `salt`, of the canonical JSON of the row content."""
    if not isinstance(salt, bytes) or not salt:
        raise ValueError("content digest salt must be non-empty bytes")
    if not isinstance(parts.config, Mapping) or not isinstance(parts.sensitive_config, Mapping):
        raise ValueError("config and sensitive_config must be objects")
    if not isinstance(parts.errors, str):
        raise ValueError("errors must be a string")
    if parts.external_id is not None and not isinstance(parts.external_id, str):
        raise ValueError("external_id must be a string or None")
    if not isinstance(parts.unreadable_keys, Sequence) or isinstance(parts.unreadable_keys, str | bytes):
        raise ValueError("unreadable_keys must be a sequence of strings")
    unreadable_keys = list(parts.unreadable_keys)
    if not all(isinstance(key, str) for key in unreadable_keys):
        raise ValueError("unreadable_keys must be a sequence of strings")
    payload = {
        "v": CONTENT_DIGEST_VERSION,
        "config": dict(parts.config),
        "errors": parts.errors,
        "external_id": parts.external_id,
        "sensitive_config": dict(parts.sensitive_config),
        "unreadable_keys": _utf16_sorted(unreadable_keys),
    }
    return hmac.new(salt, canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()


def _utf16_sorted(keys: Any) -> list[str]:
    # JS sorts by UTF-16 code units, which puts astral characters before U+E000-U+FFFF.
    return sorted(keys, key=lambda key: key.encode("utf-16-be", "surrogatepass"))


def _as_js_string(value: str) -> str:
    # Joins a surrogate pair held as two code points into one character, as a JS string sees it.
    return value.encode("utf-16-be", "surrogatepass").decode("utf-16-be", "surrogatepass")


def _escape(match: re.Match[str]) -> str:
    char = match.group()
    return _ESCAPES.get(char) or f"\\u{ord(char):04x}"


def _string(value: str) -> str:
    return '"' + _NEEDS_ESCAPE.sub(_escape, _as_js_string(value)) + '"'


def _number(value: int | float) -> str:
    """ECMAScript Number::toString of the nearest IEEE double."""
    try:
        number = float(value)
    except OverflowError:
        raise ValueError("canonical JSON cannot encode an integer outside the double range")
    if not math.isfinite(number):
        raise ValueError("canonical JSON cannot encode a non-finite number")
    if isinstance(value, int) and int(number) != value:
        raise ValueError("canonical JSON cannot encode an integer that a double cannot hold exactly")
    if number == 0:
        return "0"
    # repr gives the shortest digits that round-trip, the same digits ECMAScript picks.
    decimal = Decimal(repr(abs(number))).as_tuple()
    digits = "".join(map(str, decimal.digits))
    stripped = digits.rstrip("0")
    exponent = int(decimal.exponent) + len(digits) - len(stripped)
    digits = stripped
    k = len(digits)
    n = k + exponent
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        mantissa = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        text = f"{mantissa}e{'+' if n > 0 else '-'}{abs(n - 1)}"
    return "-" + text if number < 0 else text
