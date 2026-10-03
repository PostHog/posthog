import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from functools import cached_property

from posthog.dataclasses import frozen

from .event import TraceEvent
from .usage import Usage


@frozen(slots=False)
class TreeNode:
    event: TraceEvent
    children: tuple["TreeNode", ...]

    @cached_property
    def rolled_up_usage(self) -> Usage:
        return self.event.usage.rolled_up([child.contributed_usage for child in self.children])

    @property
    def contributed_usage(self) -> Usage:
        return self.rolled_up_usage if self.children else self.event.usage

    @property
    def display_usage(self) -> Usage:
        # A generation's stats describe its own model call, so only other nodes show their subtree's roll-up.
        if not self.children or self.event.kind == "generation":
            return self.event.usage
        rolled = self.rolled_up_usage
        return Usage(
            cost_usd=rolled.cost_usd,
            latency_s=rolled.latency_s,
            input_tokens=rolled.input_tokens or None,
            output_tokens=rolled.output_tokens or None,
            cache_read_tokens=rolled.cache_read_tokens,
            cache_write_tokens=rolled.cache_write_tokens,
        )


def build_tree(events: Sequence[TraceEvent], trace_id: str) -> tuple[TreeNode, ...]:
    nodes = [event for event in events if not event.is_annotation and not event.is_trace_event]
    known_keys = {event.node_key for event in nodes}

    def order(event: TraceEvent) -> tuple[datetime, float]:
        latency = event.row.latency
        return event.started_at, -(latency if latency is not None and math.isfinite(latency) else 0)

    ordered = sorted(nodes, key=order)
    children_of: defaultdict[str, list[TraceEvent]] = defaultdict(list)
    for event in ordered:
        if event.parent_key != event.node_key:
            children_of[event.parent_key].append(event)

    reached: set[str] = set()

    def build(event: TraceEvent) -> TreeNode:
        reached.add(event.id)
        # Popping the bucket hands every child to the first node built with this key, so events that share
        # the key never scan it again.
        bucket = children_of.pop(event.node_key, [])
        return TreeNode(event=event, children=tuple(build(child) for child in bucket if child.id not in reached))

    roots = [
        event
        for event in ordered
        if event.parent_key in (trace_id, event.node_key) or event.parent_key not in known_keys
    ]
    built = [build(root) for root in roots if root.id not in reached]
    # Members of a parent cycle have no root above them, so they would vanish without this pass.
    built += [build(event) for event in ordered if event.id not in reached]
    return tuple(built)
