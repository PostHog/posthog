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

# ClickHouse prints each timestamp clause of the Min-Max condition as `timestamp in [A, +Inf)`,
# `timestamp in (-Inf, B]` or `timestamp in [A, B]`, in unix seconds. A range with a start and an
# end comes as two clauses under `and(...)`, the end first, so every clause is read.
_BOUND_RE = re.compile(r"in\s*[\[\(]\s*([^,\[\(]+?)\s*,\s*([^\]\)]+?)\s*[\]\)]")


@frozen
class TimestampBounds:
    """The timestamp range the Min-Max step could bound, in unix seconds. None means unbounded."""

    lower: int | None
    upper: int | None


@frozen
class PlanIndex:
    """One entry of a read node's ``Indexes`` list."""

    type: str
    keys: tuple[str, ...]
    condition: str | None
    initial_granules: int | None
    selected_granules: int | None


@frozen
class PlanTableRead:
    """One ``ReadFromMergeTree`` node. ``table`` is the node's Description."""

    table: str
    indexes: tuple[PlanIndex, ...]

    def reads_events(self) -> bool:
        return self._matches(_EVENTS_TABLE_NAMES)

    def reads_persons(self) -> bool:
        return self._matches(_PERSON_TABLE_NAMES)

    def _matches(self, names: tuple[str, ...]) -> bool:
        # The database qualifier is optional; a longer name that only ends in one of these is another table.
        return any(self.table == name or self.table.endswith(f".{name}") for name in names)

    def average_rows_per_granule(self, averages: dict[str, float]) -> float | None:
        # The map is keyed by bare table name, and the plan's Description keeps the database qualifier.
        return next((average for name, average in averages.items() if self._matches((name,))), None)

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

    def timestamp_bounds(self) -> TimestampBounds:
        step = self.min_max()
        if step is None or step.condition is None or not any("timestamp" in key for key in step.keys):
            return TimestampBounds(lower=None, upper=None)
        return _parse_timestamp_bounds(step.condition)


@frozen
class QueryPlan:
    reads: tuple[PlanTableRead, ...]

    def events_reads(self) -> tuple[PlanTableRead, ...]:
        return tuple(read for read in self.reads if read.reads_events())

    def heaviest_events_read(self) -> PlanTableRead | None:
        """The events read that kept the most granules. A query can read the events table more than
        once, through a join or a union, and the largest read is the one that made it slow.
        """
        reads = self.events_reads()
        if not reads:
            return None
        return max(reads, key=lambda read: read.selected_granules() or 0)

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
    _collect_reads(payload, reads)
    return QueryPlan(reads=tuple(reads))


def _collect_reads(node: object, reads: list[PlanTableRead]) -> None:
    """Append every MergeTree read under ``node`` to ``reads``, in plan order."""
    if isinstance(node, list):
        for item in node:
            _collect_reads(item, reads)
        return
    if not isinstance(node, dict):
        return
    _collect_reads(node.get("Plan"), reads)
    if node.get("Node Type") == _MERGE_TREE_READ:
        read = _parse_read(node)
        if read is not None:
            reads.append(read)
    _collect_reads(node.get("Plans"), reads)


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
    condition = entry.get("Condition")
    return PlanIndex(
        type=index_type,
        keys=tuple(key for key in keys if isinstance(key, str)) if isinstance(keys, list) else (),
        condition=condition if isinstance(condition, str) else None,
        initial_granules=_as_int(entry.get("Initial Granules")),
        selected_granules=_as_int(entry.get("Selected Granules")),
    )


def _parse_timestamp_bounds(condition: str) -> TimestampBounds:
    lowers: list[int] = []
    uppers: list[int] = []
    for match in _BOUND_RE.finditer(condition):
        lower = _bound_value(match.group(1))
        upper = _bound_value(match.group(2))
        if lower is not None:
            lowers.append(lower)
        if upper is not None:
            uppers.append(upper)
    # The clauses are ANDed, so the range they describe is their intersection.
    return TimestampBounds(lower=max(lowers, default=None), upper=min(uppers, default=None))


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
