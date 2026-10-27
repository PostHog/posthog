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
        make_row(uuid="fb-1", event="$ai_feedback", timestamp=T0 + timedelta(seconds=4)),
    ],
    None,
)


def test_matches_follow_the_tree_with_the_root_first() -> None:
    result = TraceSearchResult.of(TRACE, {"gen-2": 1, "gen-1": 4, "root-event": 2, "fb-1": 9, "span-1": 0})

    assert result == TraceSearchResult(
        total=7,
        matches=(
            NodeMatch(node_id="trace-1", count=2),
            NodeMatch(node_id="gen-1", count=4),
            NodeMatch(node_id="gen-2", count=1),
        ),
    )


def test_no_counts_is_an_empty_result() -> None:
    assert TraceSearchResult.of(TRACE, {}) == TraceSearchResult(total=0, matches=())
