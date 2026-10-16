from collections.abc import Sequence
from datetime import datetime
from functools import cached_property

from .event import TraceEvent
from .thread import pick_user_visible_generation
from .timeline import Timeline
from .trace_queries import PersonRow, TraceEventRow
from .tree import build_tree
from .usage import Usage, sum_known

BILLED_EVENTS = frozenset({"$ai_generation", "$ai_embedding"})


class Trace:
    def __init__(self, trace_id: str, rows: Sequence[TraceEventRow], person: PersonRow | None) -> None:
        self.id = trace_id
        self.person = person
        self.events = tuple(
            sorted((TraceEvent(row=row, trace_id=trace_id) for row in rows), key=lambda event: event.row.timestamp)
        )
        self.tree = build_tree(self.events, trace_id)
        self.timeline = Timeline.from_tree(self.tree)

    @property
    def created_at(self) -> datetime:
        return self.events[0].row.timestamp

    @property
    def session_id(self) -> str | None:
        return next((event.row.session_id for event in self.events if event.row.session_id), None)

    @cached_property
    def name(self) -> str | None:
        named = [event for event in self.events if event.row.span_name or event.row.trace_name]
        chosen = next((event for event in named if event.is_trace_event), named[0] if named else None)
        return (chosen.row.span_name or chosen.row.trace_name) if chosen else None

    @property
    def title(self) -> str:
        return self.name or "Trace"

    @cached_property
    def error_count(self) -> int:
        return sum(1 for event in self.events if event.has_error)

    @property
    def has_error(self) -> bool:
        return self.error_count > 0

    @cached_property
    def totals(self) -> Usage:
        billed = [event.row for event in self.events if event.row.event in BILLED_EVENTS]
        cost = sum_known(row.total_cost_usd for row in billed)
        return Usage(
            cost_usd=round(cost, 10) if cost is not None else None,
            latency_s=self._total_latency_s(),
            input_tokens=sum_known(row.input_tokens for row in billed),
            output_tokens=sum_known(row.output_tokens for row in billed),
            cache_read_tokens=sum_known(row.cache_read_input_tokens for row in billed),
            cache_write_tokens=sum_known(row.cache_creation_input_tokens for row in billed),
        )

    @cached_property
    def thread_node_ids(self) -> list[str]:
        generation = pick_user_visible_generation(self.events)
        return [generation.id] if generation else []

    @property
    def person_label(self) -> str | None:
        if self.person is None or not self.person.distinct_id:
            return None
        return self.person.email or self.person.name or self.person.distinct_id

    def _total_latency_s(self) -> float:
        # The root $ai_trace event reports the whole trace's wall clock, so its children are already inside it.
        root_latencies = [
            event.row.latency
            for event in self.events
            if event.is_trace_event and event.row.latency is not None and event.row.latency > 0
        ]
        if root_latencies:
            return round(max(root_latencies), 2)
        timed = [event for event in self.events if (event.row.latency or 0) > 0]
        if timed and all(event.kind == "generation" for event in timed):
            return round(sum(event.row.latency or 0 for event in timed), 2)
        return round(
            sum(event.row.latency or 0 for event in self.events if event.row.parent_id in (None, self.id)),
            2,
        )
