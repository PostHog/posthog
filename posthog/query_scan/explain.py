"""Read the JSON that ``EXPLAIN indexes = 1, json = 1`` returns.

ClickHouse reads a table in granules, blocks of rows it reads or skips whole, so the granules a
read kept say how much of the table it touched. The plan reports that per table and per index step.
"""

import re
import json
from typing import Any

from posthog.dataclasses import frozen

# Spelled out rather than imported, so this parser does not pull in the model layer.
_EVENTS_TABLE_NAMES = ("events", "events_json", "sharded_events", "sharded_events_json")

_PERSON_TABLE_NAMES = ("person", "person_distinct_id2", "person_distinct_id_overrides")

_MIN_MAX_TYPE = "Min-Max"
_PRIMARY_KEY_TYPE = "PrimaryKey"
_SKIP_TYPE = "Skip"
_MERGE_TREE_READ = "ReadFromMergeTree"
# The other shards' read. It carries no index report and is not a warehouse read.
_REMOTE_READ = "ReadFromRemote"

# ClickHouse prints a Min-Max timestamp condition in one canonical form: `timestamp in [A, +Inf)`,
# `timestamp in (-Inf, B]`, or `timestamp in [A, B]`, all in unix seconds.
_BOUNDS_RE = re.compile(r"in\s*[\[\(]\s*([^,\[\(]+?)\s*,\s*([^\]\)]+?)\s*[\]\)]")


@frozen
class TimestampBounds:
    """The timestamp range the Min-Max step could bound, in unix seconds. None means unbounded."""

    lower: int | None
    upper: int | None


@frozen
class PlanIndex:
    """One entry of a read node's ``Indexes`` list."""

    type: str
    # Only Skip steps carry a `Name`, the index that pruned; the other index types do not.
    name: str | None
    keys: tuple[str, ...]
    condition: str | None
    initial_parts: int | None
    selected_parts: int | None
    initial_granules: int | None
    selected_granules: int | None


@frozen
class PlanTableRead:
    """One ``ReadFromMergeTree`` node. ``table`` is the node's Description."""

    table: str
    indexes: tuple[PlanIndex, ...]

    def reads_events(self) -> bool:
        # The database qualifier is optional; a longer name that only ends in one of these is another table.
        return self._matches(_EVENTS_TABLE_NAMES)

    def reads_persons(self) -> bool:
        return self._matches(_PERSON_TABLE_NAMES)

    def _matches(self, names: tuple[str, ...]) -> bool:
        return any(self.table == name or self.table.endswith(f".{name}") for name in names)

    def average_rows_per_granule(self, averages: dict[str, float]) -> float | None:
        # The map is keyed by bare table name, so match by suffix the way `reads_persons` matches,
        # because the plan's Description keeps the database qualifier (`posthog.person`).
        for name, average in averages.items():
            if self.table == name or self.table.endswith(f".{name}"):
                return average
        return None

    def primary_key(self) -> PlanIndex | None:
        return self._first(_PRIMARY_KEY_TYPE)

    def uses_event_key(self) -> bool:
        """Whether the primary key lists `event`. The plan side of the event-filter verdict, and the fallback
        when no tree verdict shipped.
        """
        primary_key = self.primary_key()
        return primary_key is not None and "event" in primary_key.keys

    def min_max(self) -> PlanIndex | None:
        return self._first(_MIN_MAX_TYPE)

    def _first(self, index_type: str) -> PlanIndex | None:
        for index in self.indexes:
            if index.type == index_type:
                return index
        return None

    def skip_steps(self) -> tuple[PlanIndex, ...]:
        return tuple(index for index in self.indexes if index.type == _SKIP_TYPE)

    def selected_granules(self) -> int | None:
        """The granules the read kept after its last index step."""
        for index in reversed(self.indexes):
            if index.selected_granules is not None:
                return index.selected_granules
        return None

    def has_timestamp_key(self) -> bool:
        step = self.min_max()
        return step is not None and any("timestamp" in key for key in step.keys)

    def timestamp_bounds(self) -> TimestampBounds:
        step = self.min_max()
        if step is None or step.condition is None or not self.has_timestamp_key():
            return TimestampBounds(lower=None, upper=None)
        return _parse_timestamp_bounds(step.condition)


@frozen
class QueryPlan:
    reads: tuple[PlanTableRead, ...]
    has_non_mergetree_read: bool = False

    def events_reads(self) -> tuple[PlanTableRead, ...]:
        return tuple(read for read in self.reads if read.reads_events())

    def events_read(self) -> PlanTableRead | None:
        return next(iter(self.events_reads()), None)

    def event_key_used(self) -> bool | None:
        """Whether every events read pruned on `event`. None when the plan has no events read,
        so the tree's verdict is left to stand."""
        reads = self.events_reads()
        if not reads:
            return None
        return all(read.uses_event_key() for read in reads)

    def person_reads(self) -> tuple[PlanTableRead, ...]:
        return tuple(read for read in self.reads if read.reads_persons())


def parse_query_plan(payload: object) -> QueryPlan:
    """Never raises: an unexpected shape yields a plan with no reads."""
    if isinstance(payload, str | bytes | bytearray):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return QueryPlan(reads=())

    reads: list[PlanTableRead] = []
    saw_other_read = _collect_reads(payload, reads)
    return QueryPlan(reads=tuple(reads), has_non_mergetree_read=saw_other_read)


def _collect_reads(node: object, reads: list[PlanTableRead]) -> bool:
    """Append every MergeTree read to ``reads``; return whether a non-MergeTree read node was seen."""
    if isinstance(node, list):
        # Visit every item, not `any(...)`, which would stop appending reads at the first non-MergeTree.
        saw_other = False
        for item in node:
            saw_other = _collect_reads(item, reads) or saw_other
        return saw_other
    if not isinstance(node, dict):
        return False

    saw_other = _collect_reads(node.get("Plan"), reads)

    node_type = node.get("Node Type")
    if node_type == _MERGE_TREE_READ:
        read = _parse_read(node)
        if read is not None:
            reads.append(read)
    elif isinstance(node_type, str) and node_type.startswith("ReadFrom") and node_type != _REMOTE_READ:
        saw_other = True

    return _collect_reads(node.get("Plans"), reads) or saw_other


def _parse_read(node: dict[str, Any]) -> PlanTableRead | None:
    table = node.get("Description")
    if not isinstance(table, str):
        return None
    indexes = node.get("Indexes")
    parsed_indexes: list[PlanIndex] = []
    if isinstance(indexes, list):
        for entry in indexes:
            parsed = _parse_index(entry)
            if parsed is not None:
                parsed_indexes.append(parsed)
    return PlanTableRead(table=table, indexes=tuple(parsed_indexes))


def _parse_index(entry: object) -> PlanIndex | None:
    if not isinstance(entry, dict):
        return None
    index_type = entry.get("Type")
    if not isinstance(index_type, str):
        return None
    keys = entry.get("Keys")
    name = entry.get("Name")
    condition = entry.get("Condition")
    return PlanIndex(
        type=index_type,
        name=name if isinstance(name, str) else None,
        keys=tuple(key for key in keys if isinstance(key, str)) if isinstance(keys, list) else (),
        condition=condition if isinstance(condition, str) else None,
        initial_parts=_as_int(entry.get("Initial Parts")),
        selected_parts=_as_int(entry.get("Selected Parts")),
        initial_granules=_as_int(entry.get("Initial Granules")),
        selected_granules=_as_int(entry.get("Selected Granules")),
    )


def _parse_timestamp_bounds(condition: str) -> TimestampBounds:
    match = _BOUNDS_RE.search(condition)
    if match is None:
        return TimestampBounds(lower=None, upper=None)
    return TimestampBounds(lower=_bound_value(match.group(1)), upper=_bound_value(match.group(2)))


def _bound_value(token: str) -> int | None:
    token = token.strip()
    if token.lstrip("+-").lower() == "inf":
        return None
    try:
        return int(float(token))
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
