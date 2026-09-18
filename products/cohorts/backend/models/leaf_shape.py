import json
import hashlib
from collections.abc import Iterator
from enum import StrEnum
from typing import Literal, NamedTuple

from posthog.dataclasses import frozen

_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1

RepairKind = Literal["behavioral", "person_property"]


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


class _LeafShapeMode(StrEnum):
    BEHAVIORAL_ONLY = "behavioral_only"
    PERSON_ONLY = "person_only"


def _extract_leaf_shape_keys(filters: dict | None, *, mode: _LeafShapeMode) -> list[list[object]]:
    if not filters or not (properties := filters.get("properties")):
        return []

    keys: list[list[object]] = []
    for leaf in walk_filter_leaves(properties):
        leaf_type = leaf.get("type")
        if leaf_type == "person" and mode == _LeafShapeMode.PERSON_ONLY:
            if (condition_hash := leaf.get("conditionHash")) is not None:
                keys.append(["person", condition_hash])
        elif leaf_type == "behavioral" and mode == _LeafShapeMode.BEHAVIORAL_ONLY:
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
    return keys


def _canonical(node: object) -> str:
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def _render_definition(node: object, *, person_view: bool = False) -> list[object] | None:
    """Render one filter node into an order-insensitive, JSON-serializable form, or `None` if it
    contributes nothing to the definition.

    `person_view` renders the tree as a person backfill run sees it. The seeder pins only person
    leaves and holds every other leaf unknown while deciding whether a person's leaf truths can move
    the cohort (`rust/cohort-seeder/src/domain/person_relevance.rs`), and an unknown reads the same
    whatever the leaf says or whether it is negated, so every non-person leaf renders as one
    anonymous marker and the group dedupe collapses any number of them into one.

    Group children are deduped and sorted because AND and OR are commutative and idempotent, so a
    reordered or repeated criterion is the same definition. A group of one operand renders as that
    operand: the cohort editor shows its AND/OR toggle even on a single criterion, and a toggle with
    one operand under it means nothing.

    Cohort references are negated by `negation` or by `operator: "not_in"`, which mirrors
    `cohort_ref_negation` in `rust/cohort-core/src/filters/leaf_classifier.rs`. Person and
    behavioral leaves are negated by `negation` alone, because a bare `not_in` on those is a
    value-list predicate already compiled into the bytecode the conditionHash digests.

    `is True` rather than `bool(...)` for the same reason `_effective_i32` rejects a non-int: Rust
    reads the field with `as_bool().unwrap_or(false)`, so a non-boolean is absent there, and
    `bool(1)` here would disagree.
    """
    if not isinstance(node, dict):
        return None

    node_type = node.get("type")
    if node_type in ("AND", "OR"):
        unique: dict[str, list[object]] = {}
        for child in node.get("values") or []:
            if (rendered := _render_definition(child, person_view=person_view)) is not None:
                unique.setdefault(_canonical(rendered), rendered)
        # Rust retains empty groups and excludes their cohort from realtime evaluation.
        children = [unique[key] for key in sorted(unique)]
        if len(children) == 1:
            return children[0]
        return [node_type, children]

    negation = node.get("negation") is True
    if node_type == "person":
        return ["person", node.get("conditionHash"), negation]
    if person_view:
        return ["unknown"]
    if node_type == "behavioral":
        return [
            "behavioral",
            *behavioral_leaf_key(
                condition_hash=node.get("conditionHash"),
                value=node.get("value"),
                time_value=node.get("time_value"),
                time_interval=node.get("time_interval"),
                explicit_datetime=node.get("explicit_datetime"),
                explicit_datetime_to=node.get("explicit_datetime_to"),
                operator=node.get("operator"),
                operator_value=node.get("operator_value"),
            ),
            negation,
        ]
    if node_type == "cohort":
        return ["cohort", node.get("value"), negation or node.get("operator") == "not_in"]
    return [node_type]


def extract_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint the whole cohort definition: every leaf, its negation, and the AND/OR tree it
    sits in, order-insensitive.

    This is the only fingerprint that sees composition. The two kind hashes below key on leaf
    identity alone, so an edit that only moves AND/OR, negation, or a nested-cohort reference moves
    this hash and neither of theirs. Saves and readiness stamps use `FilterShapeHashes` to agree
    on which kind must repair a definition change that no leaf hash would trigger.
    Keep the leaf fields in lockstep with Rust: behavioral leaves via `BehavioralLeafKey`; person
    conditionHash; cohort value; the negation rules in `_render_definition`.
    """
    return _fingerprint(filters, person_view=False)


def extract_person_composition_hash(filters: dict | None) -> str:
    """Fingerprint the definition as a person backfill run sees it: person leaves by condition hash
    and negation, every other leaf one anonymous unknown, in the AND/OR tree they sit in.

    The seeder emits a person only when their leaf truths can move this tree, so the person state a
    run stores is valid for this fingerprint alone. An edit that moves it and not the person hash
    owes a person run, which `FilterShapeHashes.composition_repair_kinds` decides.
    """
    return _fingerprint(filters, person_view=True)


def _fingerprint(filters: dict | None, *, person_view: bool) -> str:
    if not filters or not (properties := filters.get("properties")):
        return ""

    rendered = _render_definition(properties, person_view=person_view)
    if rendered is None:
        return ""
    return hashlib.sha256(_canonical(rendered).encode()).hexdigest()


def extract_behavioral_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint only the leaf inputs backed by behavioral event state."""
    return _hash_keys(_extract_leaf_shape_keys(filters, mode=_LeafShapeMode.BEHAVIORAL_ONLY))


def extract_person_leaf_shape_hash(filters: dict | None) -> str:
    """Fingerprint only person-property condition hashes."""
    return _hash_keys(_extract_leaf_shape_keys(filters, mode=_LeafShapeMode.PERSON_ONLY))


@frozen
class FilterShapeHashes:
    definition: str | None
    behavioral: str | None
    person: str | None
    person_composition: str | None

    @classmethod
    def from_filters(cls, filters: dict | None) -> "FilterShapeHashes":
        return cls(
            definition=extract_leaf_shape_hash(filters),
            behavioral=extract_behavioral_leaf_shape_hash(filters),
            person=extract_person_leaf_shape_hash(filters),
            person_composition=extract_person_composition_hash(filters),
        )

    def composition_repair_kinds(self, previous: "FilterShapeHashes", filters: dict | None) -> frozenset[RepairKind]:
        """The kinds a definition change must re-run beyond the ones its leaf-hash changes already fire.

        Behavioral leaf state is per leaf and survives a composition change, so a behavioral run only
        re-reconciles the tree: one is owed when the definition moved and no leaf hash fires a run.
        A behavioral run nulls `last_backfill_events_at`. Strict flag routing reads that stamp, so
        it is the kind chosen here.

        Person state is not per leaf. The seeder emits a person only when their leaf truths can move
        the tree it pinned, so what a run stored is valid for that tree alone, and a person run is
        owed whenever the tree as the person path sees it moved and the person hash did not, whatever
        else the same save changed. It is also owed on any definition change when no behavioral run
        re-walks the tree, because it is then the only run that reconciles the cohort.
        """
        if previous.definition is None or previous.definition == self.definition:
            return frozenset()

        leaf_types = {leaf.get("type") for leaf in walk_filter_leaves((filters or {}).get("properties"))}
        person_backfillable = bool(self.person) and "person_metadata" not in leaf_types
        # Match the run creators: an unhashed behavioral leaf can trigger a run, but person metadata cannot.
        behavioral_run_fires = previous.behavioral != self.behavioral and "behavioral" in leaf_types
        person_run_fires = previous.person != self.person and person_backfillable

        behavioral_repair = bool(self.behavioral) and not behavioral_run_fires and not person_run_fires
        behavioral_run_rewalks = behavioral_run_fires or behavioral_repair

        kinds: set[RepairKind] = set()
        if behavioral_repair:
            kinds.add("behavioral")
        if person_backfillable and not person_run_fires:
            if previous.person_composition != self.person_composition or not behavioral_run_rewalks:
                kinds.add("person_property")
        return frozenset(kinds)
