from datetime import timedelta
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.event import TraceEvent
from products.ai_observability.backend.logic.traces.tree import TreeNode, build_tree
from products.ai_observability.backend.logic.traces.usage import Usage

from .rows import T0, make_row


def events(*rows: dict[str, Any]) -> list[TraceEvent]:
    return [TraceEvent(row=make_row(**row), trace_id="trace-1") for row in rows]


def shape(nodes: tuple[TreeNode, ...]) -> list[Any]:
    return [(node.event.id, shape(node.children)) for node in nodes]


def test_nests_by_parent_and_orders_siblings_by_operation_start() -> None:
    tree = build_tree(
        events(
            {"uuid": "late", "span_id": "late", "timestamp": T0 + timedelta(seconds=5)},
            {"uuid": "early", "span_id": "early", "timestamp": T0 + timedelta(seconds=5), "latency": 4.0},
            {"uuid": "child", "parent_id": "early", "timestamp": T0 + timedelta(seconds=3)},
        ),
        "trace-1",
    )

    assert shape(tree) == [("early", [("child", [])]), ("late", [])]


def test_promotes_orphans_to_roots_including_children_of_the_trace_event_span() -> None:
    tree = build_tree(
        events(
            {"uuid": "trace-event", "event": "$ai_trace", "span_id": "root-span", "parent_id": None},
            {"uuid": "orphan", "span_id": "span-1", "parent_id": "root-span"},
            {"uuid": "grandchild", "parent_id": "span-1", "timestamp": T0 + timedelta(seconds=1)},
        ),
        "trace-1",
    )

    assert shape(tree) == [("orphan", [("grandchild", [])])]


def test_excludes_feedback_metric_and_trace_events() -> None:
    tree = build_tree(
        events(
            {"uuid": "span"},
            {"uuid": "feedback", "event": "$ai_feedback"},
            {"uuid": "metric", "event": "$ai_metric"},
            {"uuid": "trace-event", "event": "$ai_trace", "parent_id": None},
        ),
        "trace-1",
    )

    assert shape(tree) == [("span", [])]


def ids(nodes: tuple[TreeNode, ...]) -> list[str]:
    return [item for node in nodes for item in [node.event.id, *ids(node.children)]]


def test_keeps_parent_cycle_members_without_duplicating_any_event() -> None:
    tree = build_tree(
        events(
            {"uuid": "a", "span_id": "a", "parent_id": "b"},
            {"uuid": "b", "span_id": "b", "parent_id": "a"},
            {"uuid": "c", "span_id": "c"},
        ),
        "trace-1",
    )

    assert tree[0].event.id == "c"
    assert sorted(ids(tree)) == ["a", "b", "c"]


def test_a_self_parented_event_is_a_root() -> None:
    tree = build_tree(events({"uuid": "loop", "span_id": "loop", "parent_id": "loop"}), "trace-1")

    assert shape(tree) == [("loop", [])]


@parameterized.expand([("a pair", 2), ("thousands", 2_000)])
def test_events_sharing_a_span_id_each_appear_and_share_children_once(_name: str, count: int) -> None:
    sharing = [{"uuid": f"dup-{i}", "span_id": "s", "timestamp": T0 + timedelta(seconds=i)} for i in range(count)]
    children = [{"uuid": f"child-{i}", "parent_id": "s", "timestamp": T0 + timedelta(seconds=i)} for i in range(count)]

    tree = build_tree(events(*sharing, *children), "trace-1")

    assert [node.event.id for node in tree] == [f"dup-{i}" for i in range(count)]
    assert [child.event.id for child in tree[0].children] == [f"child-{i}" for i in range(count)]
    assert all(not node.children for node in tree[1:])


def test_a_non_finite_latency_does_not_break_ordering() -> None:
    tree = build_tree(
        events(
            {"uuid": "nan", "latency": float("nan")},
            {"uuid": "slow", "latency": 2.0, "timestamp": T0 + timedelta(seconds=2)},
        ),
        "trace-1",
    )

    assert ids(tree) == ["slow", "nan"]


def span_with(*children: dict[str, Any], **span: Any) -> TreeNode:
    rows = [{"uuid": "span", "span_id": "span", **span}]
    rows += [{"event": "$ai_generation", "parent_id": "span", **child} for child in children]
    return build_tree(events(*rows), "trace-1")[0]


def test_span_cost_stays_unknown_when_no_child_reports_one() -> None:
    assert span_with({"uuid": "g"}).display_usage.cost_usd is None


def test_span_cost_sums_only_the_children_that_report_one() -> None:
    node = span_with({"uuid": "priced", "total_cost_usd": 0.25}, {"uuid": "unpriced"})

    assert node.display_usage.cost_usd == 0.25


def test_span_keeps_its_own_latency_instead_of_summing_children() -> None:
    node = span_with({"uuid": "g", "latency": 0.917}, latency=1.806)

    assert node.display_usage.latency_s == 1.806


def test_span_tokens_roll_up_and_a_zero_sum_reads_as_unknown() -> None:
    priced = span_with({"uuid": "a", "input_tokens": 3}, {"uuid": "b", "input_tokens": 4})
    silent = span_with({"uuid": "c"})

    assert priced.display_usage.input_tokens == 7
    assert silent.display_usage.input_tokens is None


def test_nested_spans_roll_up_through_the_middle_level() -> None:
    root = build_tree(
        events(
            {"uuid": "outer", "span_id": "outer"},
            {"uuid": "inner", "span_id": "inner", "parent_id": "outer"},
            {"uuid": "g", "event": "$ai_generation", "parent_id": "inner", "total_cost_usd": 0.1, "latency": 2.0},
        ),
        "trace-1",
    )[0]

    assert root.display_usage.cost_usd == 0.1
    assert root.display_usage.latency_s == 2.0


def test_a_generation_with_children_shows_its_own_call() -> None:
    root = build_tree(
        events(
            {"uuid": "gen", "event": "$ai_generation", "generation_id": "gen", "latency": 1.0},
            {"uuid": "tool", "parent_id": "gen", "latency": 3.0},
        ),
        "trace-1",
    )[0]

    assert root.display_usage == Usage(latency_s=1.0)
