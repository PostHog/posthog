from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from functools import cached_property

from posthog.dataclasses import frozen

from .event import TraceEvent
from .git import GitRef
from .node_ids import NodeIdResolver, NodeIds
from .node_labels import number_repeated_names
from .person import person_label
from .thread import pick_user_visible_generation
from .timeline import Timeline
from .trace_expression_queries import BILLED_EVENT_NAMES
from .trace_queries import PersonRow, TraceEventRow
from .trace_selection import CAPTURE_BUFFER
from .tree import TreeNode, build_tree
from .usage import Usage, sum_known


@frozen
class TraceCompleteness:
    partial: bool
    cost_and_latency_partial: bool


COMPLETE = TraceCompleteness(partial=False, cost_and_latency_partial=False)


def read_completeness(*, truncated: bool, first_timestamp: datetime, read_start: datetime | None) -> TraceCompleteness:
    """How much of a trace a read covered. `read_start` is the lower time bound of a read from the shared events
    table, and None for a read from `posthog.ai_events`, which reads a trace by id with no time bound.

    A trace whose earliest event read lands within `CAPTURE_BUFFER` of that bound may have started before it, so the
    read may have missed its first events, and with them part of its cost and latency."""
    missed_start = (
        read_start is not None and first_timestamp.astimezone(UTC) - read_start.astimezone(UTC) < CAPTURE_BUFFER
    )
    return TraceCompleteness(partial=truncated or missed_start, cost_and_latency_partial=missed_start)


class Trace:
    def __init__(
        self,
        trace_id: str,
        rows: Sequence[TraceEventRow],
        person: PersonRow | None,
        *,
        completeness: TraceCompleteness = COMPLETE,
    ) -> None:
        self.id = trace_id
        self.person = person
        self.partial = completeness.partial
        self.cost_and_latency_partial = completeness.cost_and_latency_partial
        self.events = tuple(
            sorted((TraceEvent(row=row, trace_id=trace_id) for row in rows), key=lambda event: event.row.timestamp)
        )

    @cached_property
    def tree(self) -> tuple[TreeNode, ...]:
        return build_tree(self.events, self.id)

    @cached_property
    def timeline(self) -> Timeline:
        return Timeline.from_tree(self.tree)

    @property
    def created_at(self) -> datetime:
        return self.events[0].row.timestamp

    @property
    def session_id(self) -> str | None:
        return next((event.row.trace_session_id for event in self.events), None)

    @cached_property
    def name(self) -> str | None:
        named = [event for event in self.events if event.row.span_name or event.row.trace_name]
        chosen = next((event for event in named if event.is_trace_event), named[0] if named else None)
        return (chosen.row.span_name or chosen.row.trace_name) if chosen else None

    @property
    def title(self) -> str:
        return self.name or "Trace"

    @cached_property
    def node_labels(self) -> dict[str, str]:
        nodes = list(_in_tree_order(self.tree))
        ids = [self.id, *(node.event.id for node in nodes)]
        names = [self.title, *(node.event.title for node in nodes)]
        return dict(zip(ids, number_repeated_names(names), strict=True))

    @cached_property
    def error_count(self) -> int:
        return sum(1 for event in self.events if event.has_error)

    @property
    def has_error(self) -> bool:
        return self.error_count > 0

    @cached_property
    def first_error_text(self) -> str | None:
        return next((event.row.error_text for event in self.events if event.has_error and event.row.error_text), None)

    @cached_property
    def tools_called(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(tool for event in self.events for tool in event.row.tools_called))

    @cached_property
    def is_support_trace(self) -> bool:
        return any(event.row.is_support for event in self.events)

    @cached_property
    def totals(self) -> Usage:
        billed = [event.row for event in self.events if event.row.event in BILLED_EVENT_NAMES]
        cost = next((event.row.trace_cost_usd for event in self.events), None)
        return Usage(
            cost_usd=round(cost, 10) if cost is not None else None,
            latency_s=next((event.row.trace_latency_s for event in self.events), None),
            input_tokens=sum_known(row.input_tokens for row in billed),
            output_tokens=sum_known(row.output_tokens for row in billed),
            cache_read_tokens=sum_known(row.cache_read_input_tokens for row in billed),
            cache_write_tokens=sum_known(row.cache_creation_input_tokens for row in billed),
        )

    @cached_property
    def thread_node_ids(self) -> list[str]:
        generation = pick_user_visible_generation(self.events)
        return [generation.id] if generation else []

    @cached_property
    def default_node_id(self) -> str:
        if any(event.is_trace_event and event.row.has_state for event in self.events):
            return self.id
        return next(iter(self.thread_node_ids), None) or next((node.event.id for node in self.tree), self.id)

    @cached_property
    def node_ids_by_alias(self) -> dict[str, str]:
        return NodeIdResolver(
            NodeIds(uuid=event.id, generation_id=event.row.generation_id, span_id=event.row.span_id)
            for event in self.events
            if not event.is_trace_event
        ).aliases

    @cached_property
    def git(self) -> GitRef | None:
        return GitRef.from_rows(event.row for event in self.events)

    @property
    def person_label(self) -> str | None:
        if self.person is None or not self.person.distinct_id:
            return None
        return person_label(self.person)


def _in_tree_order(nodes: Sequence[TreeNode]) -> Iterator[TreeNode]:
    for node in nodes:
        yield node
        yield from _in_tree_order(node.children)
