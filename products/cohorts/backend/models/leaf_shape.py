import json
import hashlib
from collections.abc import Iterator

_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1


def walk_filter_leaves(node: object) -> Iterator[dict]:
    if not isinstance(node, dict):
        return
    if node.get("type") in ("AND", "OR"):
        for child in node.get("values") or []:
            yield from walk_filter_leaves(child)
    else:
        yield node


def _effective_i32(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and _I32_MIN <= value <= _I32_MAX else 0


def _effective_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _hash_keys(keys: list[list[object]]) -> str:
    if not keys:
        return ""

    serialized = sorted(json.dumps(key, sort_keys=True) for key in keys)
    return hashlib.sha256(json.dumps(serialized, separators=(",", ":")).encode()).hexdigest()


def _extract_leaf_shape_keys(filters: dict | None, *, behavioral_only: bool) -> list[list[object]]:
    if not filters or not (properties := filters.get("properties")):
        return []

    keys: list[list[object]] = []
    for leaf in walk_filter_leaves(properties):
        leaf_type = leaf.get("type")
        if leaf_type == "person" and not behavioral_only:
            if (condition_hash := leaf.get("conditionHash")) is not None:
                keys.append(["person", condition_hash])
        elif leaf_type == "behavioral":
            if (condition_hash := leaf.get("conditionHash")) is not None:
                keys.append(
                    [
                        "behavioral",
                        condition_hash,
                        _effective_string(leaf.get("value")),
                        _effective_i32(leaf.get("time_value")),
                        _effective_string(leaf.get("time_interval")),
                        _effective_string(leaf.get("explicit_datetime")),
                        _effective_string(leaf.get("explicit_datetime_to")),
                        _effective_string(leaf.get("operator")),
                        _effective_i32(leaf.get("operator_value")),
                    ]
                )
        elif leaf_type == "cohort" and not behavioral_only:
            keys.append(["cohort", leaf.get("value"), bool(leaf.get("negation", False))])
    return keys


def extract_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint the leaf fields that feed the Stage 1 `LeafStateKey`.

    This is not the Rust key itself. It is a stable SHA-256 over the full leaf set, while
    `LeafStateKey::for_behavioral` uses a 16-byte digest of one leaf. Keep these fields in lockstep:
    behavioral conditionHash, value, time_value, time_interval, explicit_datetime,
    explicit_datetime_to, operator, operator_value; person conditionHash; cohort value and negation.
    """
    return _hash_keys(_extract_leaf_shape_keys(filters, behavioral_only=False))


def extract_behavioral_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint only the leaf inputs backed by behavioral event state."""
    return _hash_keys(_extract_leaf_shape_keys(filters, behavioral_only=True))
