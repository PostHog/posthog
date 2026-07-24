import json
import hashlib
from collections.abc import Iterator
from typing import NamedTuple

_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1


class BehavioralLeafKey(NamedTuple):
    """The behavioral-leaf fields Stage 1 hashes into a `LeafStateKey`.

    `conditionHash` alone is not a leaf identity: it digests only the event matcher, so two leaves
    that differ in window, operator, or value share it (`rust/cohort-core/src/leaf_state/key.rs`).
    Anything that has to tell one leaf's state from another's — the processor's state keying, the
    shape hash below, the recompute oracle's per-leaf member sets — must key on this whole tuple.
    """

    condition_hash: object
    value: str
    time_value: int
    time_interval: str
    explicit_datetime: str
    explicit_datetime_to: str
    operator: str
    operator_value: int


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


def behavioral_leaf_key(
    *,
    condition_hash: object,
    value: object,
    time_value: object,
    time_interval: object,
    explicit_datetime: object,
    explicit_datetime_to: object,
    operator: object,
    operator_value: object,
) -> BehavioralLeafKey:
    """Normalize one behavioral leaf's raw filter fields into its `BehavioralLeafKey`.

    Coercion mirrors the Rust deserializer the processor keys state with: non-string reads as absent
    (`opt_string`) and non-`i32` reads as absent (`as_i64` into `i32`). `condition_hash` passes
    through unchanged — it is already a 16-byte digest and callers validate it.
    """
    return BehavioralLeafKey(
        condition_hash=condition_hash,
        value=_effective_string(value),
        time_value=_effective_i32(time_value),
        time_interval=_effective_string(time_interval),
        explicit_datetime=_effective_string(explicit_datetime),
        explicit_datetime_to=_effective_string(explicit_datetime_to),
        operator=_effective_string(operator),
        operator_value=_effective_i32(operator_value),
    )


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
                        *behavioral_leaf_key(
                            condition_hash=condition_hash,
                            value=leaf.get("value"),
                            time_value=leaf.get("time_value"),
                            time_interval=leaf.get("time_interval"),
                            explicit_datetime=leaf.get("explicit_datetime"),
                            explicit_datetime_to=leaf.get("explicit_datetime_to"),
                            operator=leaf.get("operator"),
                            operator_value=leaf.get("operator_value"),
                        ),
                    ]
                )
        elif leaf_type == "cohort" and not behavioral_only:
            keys.append(["cohort", leaf.get("value"), bool(leaf.get("negation", False))])
    return keys


def extract_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint the leaf fields that feed the Stage 1 `LeafStateKey`.

    This is not the Rust key itself. It is a stable SHA-256 over the full leaf set, while
    `LeafStateKey::for_behavioral` uses a 16-byte digest of one leaf. Keep these fields in lockstep:
    behavioral leaves via `BehavioralLeafKey`; person conditionHash; cohort value and negation.
    """
    return _hash_keys(_extract_leaf_shape_keys(filters, behavioral_only=False))


def extract_behavioral_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint only the leaf inputs backed by behavioral event state."""
    return _hash_keys(_extract_leaf_shape_keys(filters, behavioral_only=True))
