import json
import hashlib
from collections.abc import Iterator


def walk_filter_leaves(node: object) -> Iterator[dict]:
    if not isinstance(node, dict):
        return
    if node.get("type") in ("AND", "OR"):
        for child in node.get("values") or []:
            yield from walk_filter_leaves(child)
    else:
        yield node


def extract_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint the leaf fields that feed the Stage 1 `LeafStateKey`.

    This is not the Rust key itself. It is a stable SHA-256 over the full leaf set, while
    `LeafStateKey::for_behavioral` uses a 16-byte digest of one leaf. Keep these fields in lockstep:
    behavioral conditionHash, value, time_value, time_interval, explicit_datetime,
    explicit_datetime_to, operator, operator_value; person conditionHash; cohort value and negation.
    """
    if not filters or not (properties := filters.get("properties")):
        return ""

    keys: list[list[object]] = []
    for leaf in walk_filter_leaves(properties):
        leaf_type = leaf.get("type")
        if leaf_type == "person":
            if (condition_hash := leaf.get("conditionHash")) is not None:
                keys.append(["person", condition_hash])
        elif leaf_type == "behavioral":
            if (condition_hash := leaf.get("conditionHash")) is not None:
                keys.append(
                    [
                        "behavioral",
                        condition_hash,
                        leaf.get("value"),
                        leaf.get("time_value"),
                        leaf.get("time_interval"),
                        leaf.get("explicit_datetime"),
                        leaf.get("explicit_datetime_to"),
                        leaf.get("operator"),
                        leaf.get("operator_value"),
                    ]
                )
        elif leaf_type == "cohort":
            keys.append(["cohort", leaf.get("value"), bool(leaf.get("negation", False))])

    if not keys:
        return ""

    serialized = sorted(json.dumps(key, sort_keys=True) for key in keys)
    return hashlib.sha256(json.dumps(serialized, separators=(",", ":")).encode()).hexdigest()
