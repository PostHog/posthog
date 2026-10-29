from datetime import timedelta

from products.ai_observability.backend.logic.traces.trace import Trace
from products.ai_observability.backend.logic.traces.trace_search import NodeMatch, TraceSearchResult

from .rows import T0, make_row

TRACE = Trace(
    "trace-1",
    [
        make_row(uuid="root-event", event="$ai_trace", parent_id=None, timestamp=T0),
        make_row(uuid="span-1", span_id="s1", timestamp=T0 + timedelta(seconds=1)),
        make_row(uuid="gen-1", event="$ai_generation", parent_id="s1", timestamp=T0 + timedelta(seconds=2)),
        make_row(uuid="gen-2", event="$ai_generation", timestamp=T0 + timedelta(seconds=3)),
    ],
    None,
)


def test_matches_follow_the_tree_with_the_root_first() -> None:
    result = TraceSearchResult.of(TRACE, {"gen-2": 1, "gen-1": 4, "root-event": 2, "span-1": 0}, "trace")

    assert result == TraceSearchResult(
        total=7,
        matches=(
            NodeMatch(node_id="trace-1", count=2),
            NodeMatch(node_id="gen-1", count=4),
            NodeMatch(node_id="gen-2", count=1),
        ),
    )


def test_no_counts_is_an_empty_result() -> None:
    assert TraceSearchResult.of(TRACE, {}, "trace") == TraceSearchResult(total=0, matches=())


def test_without_a_trace_event_the_root_counts_its_title() -> None:
    trace = Trace("trace-1", [make_row(uuid="span-1", span_name="Fetch invoice", timestamp=T0)], None)

    assert TraceSearchResult.of(trace, {"span-1": 1}, "INVOICE") == TraceSearchResult(
        total=2, matches=(NodeMatch(node_id="trace-1", count=1), NodeMatch(node_id="span-1", count=1))
    )
