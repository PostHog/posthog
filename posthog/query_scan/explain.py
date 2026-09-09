"""Read the JSON that ``EXPLAIN indexes = 1, json = 1`` returns for a query.

The plan tells us which primary key columns ClickHouse actually used, which the query tree
alone cannot: ClickHouse drops a filter from the key condition when it cannot evaluate it
against the sort order, and the tree still shows the filter.
"""

import json
from typing import Any

from posthog.dataclasses import frozen

# The events read prints as the sharded table on a cluster and as the plain table on a single node.
_EVENTS_DESCRIPTION_SUFFIXES = ("sharded_events", ".events")
_PERSON_DESCRIPTION_SUFFIX = ".person"

_PRIMARY_KEY_INDEX_TYPE = "PrimaryKey"
_READ_NODE_TYPE = "ReadFromMergeTree"


@frozen
class PlanIndex:
    """One entry of a read node's ``Indexes`` list."""

    type: str
    keys: tuple[str, ...]
    condition: str | None
    initial_parts: int | None
    selected_parts: int | None
    initial_granules: int | None
    selected_granules: int | None


@frozen
class PlanTableRead:
    """One ``ReadFromMergeTree`` node."""

    description: str
    node_id: str | None
    indexes: tuple[PlanIndex, ...]

    def primary_key(self) -> PlanIndex | None:
        for index in self.indexes:
            if index.type == _PRIMARY_KEY_INDEX_TYPE:
                return index
        return None

    def reads_events(self) -> bool:
        return self.description.endswith(_EVENTS_DESCRIPTION_SUFFIXES)

    def reads_persons(self) -> bool:
        return self.description.endswith(_PERSON_DESCRIPTION_SUFFIX)


@frozen
class QueryPlan:
    reads: tuple[PlanTableRead, ...]

    def events_reads(self) -> tuple[PlanTableRead, ...]:
        return tuple(read for read in self.reads if read.reads_events())

    def persons_reads(self) -> tuple[PlanTableRead, ...]:
        return tuple(read for read in self.reads if read.reads_persons())

    def event_key_used(self) -> bool | None:
        """Whether ClickHouse put the ``event`` column in the primary key condition.

        ``None`` when the plan holds no events read, so the caller falls back to the tree.
        Every events read must use the column, because one read that scans the whole range
        costs the same as if none of them filtered.
        """
        reads = self.events_reads()
        if not reads:
            return None
        return all(_uses_event_key(read) for read in reads)

    def persons_primary_keys(self) -> tuple[str, ...] | None:
        for read in self.persons_reads():
            primary_key = read.primary_key()
            if primary_key is not None:
                return primary_key.keys
        return None


def _uses_event_key(read: PlanTableRead) -> bool:
    primary_key = read.primary_key()
    return primary_key is not None and "event" in primary_key.keys


def parse_query_plan(payload: object) -> QueryPlan:
    """Never raises. An unexpected shape yields a plan with no reads, which reads as
    "EXPLAIN told us nothing" everywhere downstream."""
    if isinstance(payload, str | bytes | bytearray):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return QueryPlan(reads=())

    reads: list[PlanTableRead] = []
    _collect_reads(payload, reads)
    return QueryPlan(reads=tuple(reads))


def _collect_reads(node: object, reads: list[PlanTableRead]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_reads(item, reads)
        return
    if not isinstance(node, dict):
        return

    plan = node.get("Plan")
    if plan is not None:
        _collect_reads(plan, reads)

    if node.get("Node Type") == _READ_NODE_TYPE:
        read = _parse_read(node)
        if read is not None:
            reads.append(read)

    _collect_reads(node.get("Plans"), reads)


def _parse_read(node: dict[str, Any]) -> PlanTableRead | None:
    description = node.get("Description")
    if not isinstance(description, str):
        return None
    node_id = node.get("Node Id")
    indexes = node.get("Indexes")
    parsed_indexes: list[PlanIndex] = []
    if isinstance(indexes, list):
        for entry in indexes:
            parsed = _parse_index(entry)
            if parsed is not None:
                parsed_indexes.append(parsed)
    return PlanTableRead(
        description=description,
        node_id=node_id if isinstance(node_id, str) else None,
        indexes=tuple(parsed_indexes),
    )


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
        initial_parts=_as_int(entry.get("Initial Parts")),
        selected_parts=_as_int(entry.get("Selected Parts")),
        initial_granules=_as_int(entry.get("Initial Granules")),
        selected_granules=_as_int(entry.get("Selected Granules")),
    )


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
