"""Python mirror of the Rust cohort-stream-processor eligibility screen.

Predicts, per cohort, the `class` label the processor reports in
`cohort_eligibility_total` (single_leaf / stage2_composable / stage2_composable_ref /
excluded_*), plus the max behavioral window in days (used by the classifier's soundness
check and missed-emission probe cutoff).
Mirrors `rust/cohort-stream-processor/src/filters/{leaf_classifier,tree,cohort_graph}.rs`
and `src/stage1/pick_state.rs` + `src/stage2/eligibility.rs` — including known quirks
(e.g. a string `time_value` reads as absent), because the screen must predict what the
processor actually emits, not what it ideally should.

Mirrored at Rust commit 659e670e917; when those files change, re-check this module and
the golden fixture against the Rust unit tests. This screen is a stopgap: retire it in
favor of a processor `/debug/catalog` endpoint once one exists (building that endpoint
is already the plan if `excluded_*` classes ever appear in `cohort_eligibility_total`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union

SINGLE_LEAF = "single_leaf"
STAGE2_COMPOSABLE = "stage2_composable"
STAGE2_COMPOSABLE_REF = "stage2_composable_ref"
EXCLUDED_NOT_MULTI_LEAF = "excluded_not_multi_leaf"
EXCLUDED_TOP_LEVEL_NEGATION = "excluded_top_level_negation"
EXCLUDED_EMPTY_GROUP = "excluded_empty_group"
EXCLUDED_HAS_COHORT_REF = "excluded_has_cohort_ref"
EXCLUDED_CYCLE_DETECTED = "excluded_cycle_detected"
EXCLUDED_UNRESOLVED_REF = "excluded_unresolved_ref"
EXCLUDED_HAS_DROPPED_LEAF = "excluded_has_dropped_leaf"
# Not a processor metric class: the Rust loader skips these cohorts entirely.
PARSE_ERROR = "parse_error"

EMITTING_CLASSES = frozenset({SINGLE_LEAF, STAGE2_COMPOSABLE, STAGE2_COMPOSABLE_REF})

_INTERVAL_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
_INTERVAL_SECONDS = {"minute": 60, "hour": 3_600}
_RELATIVE_UNIT_DAYS = {"d": 1.0, "w": 7.0, "m": 30.0, "y": 365.0, "h": 1 / 24, "M": 1 / 1440}
_I32_MAX = 2**31 - 1


@dataclass(frozen=True)
class ScreenedCohort:
    cohort_id: int
    eligibility: str
    # Max whole-day window across kept behavioral leaves; inf for absolute explicit
    # ranges (permanent membership); None when no kept behavioral leaf.
    max_window_days: Optional[float]
    drop_reasons: tuple[str, ...] = ()

    @property
    def emits(self) -> bool:
        return self.eligibility in EMITTING_CLASSES


@dataclass(frozen=True)
class _Leaf:
    kind: str  # "person" | "behavioral" | "cohort_ref"
    negated: bool = False
    window_days: Optional[float] = None
    ref_id: Optional[int] = None

    @property
    def state_keyed(self) -> bool:
        return self.kind != "cohort_ref"


@dataclass(frozen=True)
class _Group:
    op: str  # "AND" | "OR"
    children: tuple[_Node, ...]


_Node = Union[_Group, _Leaf]


@dataclass
class _ParseFlags:
    state_keyed_leaf_count: int = 0
    has_cohort_ref: bool = False
    drop_reasons: list[str] = field(default_factory=list)
    behavioral_windows: list[float] = field(default_factory=list)
    positive_ref_targets: set[int] = field(default_factory=set)
    all_ref_targets: set[int] = field(default_factory=set)


def _opt_i32(value: Any) -> Optional[int]:
    # serde_json as_i64: integers only — bools, floats, and numeric strings read as absent.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if -(2**31) <= value <= _I32_MAX else None


def _is_absolute_datetime(raw: str) -> bool:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if parsed.tzinfo is not None:
        return True
    # Naive shapes the Rust parser accepts: bare date, T- or space-separated datetime.
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            datetime.strptime(raw, fmt)
            return True
        except ValueError:
            continue
    return False


# A resolved eviction window: kind is "days" (whole-day sliding), "seconds" (sub-day
# sliding), or "explicit" (absolute calendar range, permanent membership). `days` is the
# window length in days for the soundness check (fractional for "seconds", inf for "explicit").
@dataclass(frozen=True)
class _Window:
    kind: str
    days: float


# Mirror of the Rust Option<Option<EvictionWindow>>: `is_relative=False` means the
# string is not a relative offset at all; `is_relative=True, window=None` means a
# recognized relative grammar with no representable window (q/s units → leaf drops).
@dataclass(frozen=True)
class _RelativeParse:
    is_relative: bool
    window: Optional[_Window] = None


_NOT_RELATIVE = _RelativeParse(is_relative=False)


def _relative_offset_to_window(raw: str) -> _RelativeParse:
    """Mirror of pick_state.rs relative_offset_to_window."""
    if not raw.startswith("-"):
        return _NOT_RELATIVE
    rest = raw[1:]
    split = next((i for i, c in enumerate(rest) if not c.isdigit()), None)
    if split is None:
        return _NOT_RELATIVE
    digits, tail = rest[:split], rest[split:]
    for suffix in ("Start", "End"):
        if tail.endswith(suffix):
            tail = tail[: -len(suffix)]
            break
    try:
        count = int(digits)
    except ValueError:
        return _NOT_RELATIVE
    if count > _I32_MAX:
        return _NOT_RELATIVE
    if tail in ("q", "s"):
        return _RelativeParse(is_relative=True, window=None)
    unit_days = _RELATIVE_UNIT_DAYS.get(tail)
    if unit_days is None:
        return _NOT_RELATIVE
    if tail in ("h", "M"):
        return _RelativeParse(is_relative=True, window=_Window("seconds", count * unit_days))
    return _RelativeParse(is_relative=True, window=_Window("days", float(count * unit_days)))


def _classify_bound(raw: str) -> tuple[str, Optional[_Window]]:
    """One explicit_datetime bound → ("absolute"|"relative"|"unparseable", window)."""
    if _is_absolute_datetime(raw):
        return "absolute", None
    parsed = _relative_offset_to_window(raw)
    if parsed.is_relative:
        return "relative", parsed.window
    return "unparseable", None


def _explicit_window(from_raw: Optional[str], to_raw: Optional[str]) -> Optional[_Window]:
    """Mirror of pick_state.rs explicit_eviction_window; None = leaf drops."""
    from_kind, from_window = _classify_bound(from_raw) if from_raw is not None else (None, None)
    to_kind, _ = _classify_bound(to_raw) if to_raw is not None else (None, None)
    if from_kind == "unparseable" or to_kind == "unparseable":
        return None
    if to_kind == "relative":
        return None
    if from_kind == "relative" and to_kind == "absolute":
        return None
    if from_kind == "relative":
        return from_window  # None for q/s → drop
    return _Window("explicit", math.inf)


def _interval_window(node: Mapping[str, Any]) -> Optional[_Window]:
    interval = node.get("time_interval")
    if not isinstance(interval, str) or interval not in _INTERVAL_DAYS:
        return None
    time_value = max(_opt_i32(node.get("time_value")) or 0, 0)
    if _INTERVAL_DAYS[interval] == 0:
        return _Window("seconds", time_value * _INTERVAL_SECONDS[interval] / 86_400)
    return _Window("days", float(time_value * _INTERVAL_DAYS[interval]))


def _behavioral_window_days(node: Mapping[str, Any], value: str) -> Optional[float]:
    """The leaf's window in days, or None when the state variant is unsupported (drop)."""
    # Non-string values read as absent (Rust opt_string), so coerce before the presence check.
    explicit_from = node.get("explicit_datetime") if isinstance(node.get("explicit_datetime"), str) else None
    explicit_to = node.get("explicit_datetime_to") if isinstance(node.get("explicit_datetime_to"), str) else None
    if explicit_from is not None or explicit_to is not None:
        window = _explicit_window(explicit_from, explicit_to)
    else:
        window = _interval_window(node)

    if value == "performed_event":
        return window.days if window is not None else None
    # performed_event_multiple: only whole-day sliding windows ≥ 1 day are representable.
    if window is not None and window.kind == "days" and window.days >= 1:
        return window.days
    return None


def _valid_condition_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value.encode("utf-8")) == 16


def _classify_leaf(node: Mapping[str, Any]) -> Union[_Leaf, str]:
    """Mirror of leaf_classifier.rs classify_leaf: a kept/ref _Leaf, or a drop-reason string."""
    leaf_type = node.get("type")
    if leaf_type == "behavioral":
        return _classify_behavioral(node)
    if leaf_type == "cohort":
        return _classify_cohort_ref(node)
    if leaf_type == "person":
        return _classify_person(node)
    return "unknown_leaf_type"


def _explicit_negation(node: Mapping[str, Any]) -> bool:
    return node.get("negation") is True


def _classify_behavioral(node: Mapping[str, Any]) -> Union[_Leaf, str]:
    value = node.get("value")
    if value not in ("performed_event", "performed_event_multiple"):
        return "unsupported_behavioral_value"
    key = node.get("key")
    if isinstance(key, (int, float)) and not isinstance(key, bool):
        return "behavioral_action_key"
    if not _valid_condition_hash(node.get("conditionHash")):
        return "missing_condition_hash"
    if not isinstance(node.get("bytecode"), list):
        return "missing_bytecode"
    if not isinstance(key, str) or not key:
        return "malformed_leaf"
    window = _behavioral_window_days(node, value)
    if window is None:
        return "unsupported_state_variant"
    return _Leaf(kind="behavioral", negated=_explicit_negation(node), window_days=window)


def _classify_person(node: Mapping[str, Any]) -> Union[_Leaf, str]:
    if not _valid_condition_hash(node.get("conditionHash")):
        return "missing_condition_hash"
    if not isinstance(node.get("bytecode"), list):
        return "missing_bytecode"
    return _Leaf(kind="person", negated=_explicit_negation(node))


def _classify_cohort_ref(node: Mapping[str, Any]) -> Union[_Leaf, str]:
    value = node.get("value")
    ref_id: Optional[int] = _opt_i32(value)
    if ref_id is None and isinstance(value, str):
        try:
            candidate = int(value.strip())
        except ValueError:
            candidate = None
        if candidate is not None and -(2**31) <= candidate <= _I32_MAX:
            ref_id = candidate
    if ref_id is None:
        return "malformed_leaf"
    negation = _explicit_negation(node) or node.get("operator") == "not_in"
    return _Leaf(kind="cohort_ref", negated=negation, ref_id=ref_id)


def _parse_node(node: Any, flags: _ParseFlags) -> Optional[_Node]:
    if not isinstance(node, Mapping):
        flags.drop_reasons.append("unknown_leaf_type")
        return None
    if node.get("type") in ("AND", "OR") and isinstance(node.get("values"), list):
        children = tuple(c for c in (_parse_node(child, flags) for child in node["values"]) if c is not None)
        return _Group(op=node["type"], children=children)
    classified = _classify_leaf(node)
    if isinstance(classified, str):
        flags.drop_reasons.append(classified)
        return None
    if classified.kind == "cohort_ref":
        flags.has_cohort_ref = True
        assert classified.ref_id is not None
        flags.all_ref_targets.add(classified.ref_id)
        if not classified.negated:
            flags.positive_ref_targets.add(classified.ref_id)
    else:
        flags.state_keyed_leaf_count += 1
        if classified.window_days is not None:
            flags.behavioral_windows.append(classified.window_days)
    return classified


def _condition_negation(node: _Node) -> bool:
    if isinstance(node, _Leaf):
        return node.negated
    if node.op == "AND":
        return bool(node.children) and all(_condition_negation(c) for c in node.children)
    return any(_condition_negation(c) for c in node.children)


def _has_empty_group(node: _Node) -> bool:
    if isinstance(node, _Leaf):
        return False
    return not node.children or any(_has_empty_group(c) for c in node.children)


def _tree_leaves(node: _Node) -> list[_Leaf]:
    if isinstance(node, _Leaf):
        return [node]
    return [leaf for child in node.children for leaf in _tree_leaves(child)]


@dataclass
class _Parsed:
    root: _Node
    flags: _ParseFlags


def _parse_cohort(filters: Any) -> Optional[_Parsed]:
    if not isinstance(filters, Mapping) or "properties" not in filters:
        return None
    flags = _ParseFlags()
    root = _parse_node(filters["properties"], flags) or _Group(op="AND", children=())
    return _Parsed(root=root, flags=flags)


def _classify_cohort(parsed: _Parsed) -> str:
    """Mirror of stage2/eligibility.rs classify() — pre-ref-refinement class."""
    flags = parsed.flags
    if flags.drop_reasons:
        return EXCLUDED_HAS_DROPPED_LEAF
    if _has_empty_group(parsed.root):
        return EXCLUDED_EMPTY_GROUP
    if _condition_negation(parsed.root):
        return EXCLUDED_TOP_LEVEL_NEGATION
    if flags.has_cohort_ref:
        return EXCLUDED_HAS_COHORT_REF
    leaves = _tree_leaves(parsed.root)
    if len(leaves) == 1 and leaves[0].state_keyed:
        return SINGLE_LEAF
    if flags.state_keyed_leaf_count >= 2:
        return STAGE2_COMPOSABLE
    return EXCLUDED_NOT_MULTI_LEAF


def _find_cycles(edges: Mapping[int, set[int]]) -> set[int]:
    """Nodes in a ref cycle (SCC of size > 1, or self-loop), over all-ref edges.

    Iterative Tarjan SCC (explicit work stack instead of recursion), matching the Rust
    side's petgraph tarjan_scc.
    """
    in_cycle: set[int] = {n for n, targets in edges.items() if n in targets}
    index_counter = [0]
    stack: list[int] = []
    on_stack: set[int] = set()
    index: dict[int, int] = {}
    lowlink: dict[int, int] = {}

    def strongconnect(v: int) -> None:
        work = [(v, iter(sorted(edges.get(v, ()))))]
        index[v] = lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = lowlink[w] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(edges.get(w, ())))))
                    advanced = True
                    break
                if w in on_stack:
                    lowlink[node] = min(lowlink[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc.append(w)
                    if w == node:
                        break
                if len(scc) > 1:
                    in_cycle.update(scc)

    for node in sorted(edges):
        if node not in index:
            strongconnect(node)
    return in_cycle


def screen_team(
    cohort_filters: Mapping[int, Any],
    *,
    cascade_enabled: bool = True,
) -> dict[int, ScreenedCohort]:
    """Screen every cohort of one team, including cross-cohort ref refinement."""
    parsed: dict[int, Optional[_Parsed]] = {cid: _parse_cohort(f) for cid, f in cohort_filters.items()}
    base: dict[int, str] = {}
    for cid, p in parsed.items():
        base[cid] = PARSE_ERROR if p is None else _classify_cohort(p)

    edges = {cid: p.flags.all_ref_targets for cid, p in parsed.items() if p is not None and p.flags.all_ref_targets}
    in_cycle = _find_cycles(edges) if edges else set()

    # Ref refinement (stage2/eligibility.rs refine_ref_bearing), targets-before-referrers
    # via memo. Iterative with an explicit stack: a long acyclic reference chain must not
    # hit Python's recursion limit and crash the report.
    final: dict[int, str] = {}
    resolvable = {SINGLE_LEAF, STAGE2_COMPOSABLE, STAGE2_COMPOSABLE_REF, EXCLUDED_HAS_COHORT_REF}

    def refine(cid: int) -> str:
        stack = [cid]
        while stack:
            current = stack[-1]
            if current in final:
                stack.pop()
                continue
            cls = base.get(current)
            if cls != EXCLUDED_HAS_COHORT_REF:
                final[current] = cls if cls is not None else PARSE_ERROR
                stack.pop()
                continue
            if current in in_cycle:
                final[current] = EXCLUDED_CYCLE_DETECTED
                stack.pop()
                continue
            p = parsed[current]
            assert p is not None
            targets = sorted(p.flags.positive_ref_targets)
            # Refine known targets first; revisit `current` once they are all final.
            # Terminates because every true reference cycle is pre-marked in `in_cycle`.
            pending = [t for t in targets if t in base and t not in final]
            if pending:
                stack.extend(pending)
                continue
            if any(t not in base or final[t] not in resolvable for t in targets):
                final[current] = EXCLUDED_UNRESOLVED_REF
            else:
                final[current] = STAGE2_COMPOSABLE_REF if cascade_enabled else EXCLUDED_HAS_COHORT_REF
            stack.pop()
        return final[cid]

    result: dict[int, ScreenedCohort] = {}
    for cid, p in parsed.items():
        windows = p.flags.behavioral_windows if p is not None else []
        result[cid] = ScreenedCohort(
            cohort_id=cid,
            eligibility=refine(cid),
            max_window_days=max(windows) if windows else None,
            drop_reasons=tuple(p.flags.drop_reasons) if p is not None else (),
        )
    return result
