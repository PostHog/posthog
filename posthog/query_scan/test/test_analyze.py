from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import QueryScanFindingReason, QueryScanMode

from posthog.query_scan.analyze import PlanSet, QueryScanResult, analyze
from posthog.query_scan.event_filter import EventFilterOutcome
from posthog.query_scan.explain import QueryPlan, parse_query_plan
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.test.test_explain import events_read_node, load_plan

_USABLE_EVENT_FILTER = EventFilterOutcome(classification="usable")
_END_DATE_ONLY = "(timestamp in (-Inf, 1800000000])"
# A start and an end date, in the two-clause form ClickHouse prints them in.
_BOTH_BOUNDS = "and((timestamp in (-Inf, 1800000000]), (timestamp in [1700000000, +Inf)))"


_EVENT_KEY = ["team_id", "toDate(timestamp)", "event"]


def plan(name: str) -> QueryPlan:
    return parse_query_plan(load_plan(name))


def single_read_plan(condition: str) -> QueryPlan:
    return parse_query_plan([{"Plan": events_read_node(condition, ["timestamp"] if condition != "true" else [])}])


def join_plan(*reads: dict[str, object]) -> QueryPlan:
    return parse_query_plan([{"Plan": {"Node Type": "Join", "Plans": list(reads)}}])


def analyze_fixture(
    outer: str | QueryPlan,
    *,
    subqueries: tuple[str, ...] = (),
    team_granules: int | None = None,
    range_granules: int | None = None,
    persons_ratio: float = 0.5,
    query_kind: str = "HogQLQuery",
    open_filters_placeholder: bool = False,
    event_filter: EventFilterOutcome | None = None,
    table_row_averages: dict[str, float] | None = None,
    all_time: bool = False,
    all_history_by_design: bool = False,
) -> QueryScanResult:
    return analyze(
        PlanSet(
            outer=plan(outer) if isinstance(outer, str) else outer,
            subqueries=tuple(plan(name) for name in subqueries),
            team_granules=team_granules,
            range_granules=range_granules,
        ),
        QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=persons_ratio),
        query_kind=query_kind,
        open_filters_placeholder=open_filters_placeholder,
        event_filter=event_filter,
        table_row_averages=table_row_averages,
        all_time=all_time,
        all_history_by_design=all_history_by_design,
    )


class TestAnalyze(SimpleTestCase):
    @parameterized.expand(
        [
            # event gate: the read is a large share of the range, so the missing event filter is flagged
            (
                "no event filter, over the ratio",
                "plan_no_event_filter",
                {"range_granules": 1_000_000},
                ["no_event_filter"],
            ),
            # event gate the other way: the read is a small share, so nothing is flagged
            ("no event filter, under the ratio", "plan_no_event_filter", {"range_granules": 100_000_000}, []),
            ("event filter in the key stays quiet", "plan_event_filter_used", {}, []),
            ("event filter inside an OR still used", "plan_event_filter_in_or", {}, []),
            ("no date bound is flagged", "plan_no_date_bound", {}, ["no_start_date"]),
            # A date range with a start and an end is bounded, whatever order ClickHouse lists the two
            # clauses in; an end date on its own leaves the start open.
            (
                "a start and an end date are bounded",
                single_read_plan(_BOTH_BOUNDS),
                {"event_filter": _USABLE_EVENT_FILTER},
                [],
            ),
            (
                "an end date alone is no start date",
                single_read_plan(_END_DATE_ONLY),
                {"event_filter": _USABLE_EVENT_FILTER},
                ["no_start_date"],
            ),
            # A join reads the events table twice; the small unbounded read is the one to flag even
            # though the bounded read is the larger one and the one the shares are taken from.
            (
                "any events read with no start date is flagged",
                join_plan(
                    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=5000),
                    events_read_node("true", [], selected_granules=10),
                ),
                {"event_filter": _USABLE_EVENT_FILTER},
                ["no_start_date"],
            ),
            # The event filter is judged on the larger read: a small read without one stays quiet, and
            # a large read without one is flagged whatever the small read did.
            (
                "a lighter read with no event filter is not flagged",
                join_plan(
                    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=5000, primary_keys=_EVENT_KEY),
                    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=10),
                ),
                {"range_granules": 10_000},
                [],
            ),
            (
                "the heaviest read with no event filter is flagged",
                join_plan(
                    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=5000),
                    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=10, primary_keys=_EVENT_KEY),
                ),
                {"range_granules": 10_000},
                ["no_event_filter"],
            ),
            # An "All time" insight runs with a bound at the project's first event, so the plan alone
            # would stay quiet; the setting is what says no start date was chosen.
            (
                "all time insight is flagged despite the bound",
                "plan_event_filter_used",
                {"query_kind": "TrendsQuery", "all_time": True},
                ["no_start_date"],
            ),
            # First-time math has to read from the first event whatever the date range, so the
            # advice to set one could not be followed.
            (
                "an insight that reads all history by design gets no start-date advice",
                "plan_no_date_bound",
                {"query_kind": "TrendsQuery", "all_history_by_design": True},
                [],
            ),
            # persons gate: the persons read dwarfs the events read
            ("persons join over the ratio", "plan_persons_join", {}, ["persons_join"]),
            # persons gate the other way: raise the ratio past what the plan shows
            ("persons join under the ratio", "plan_persons_join", {"persons_ratio": 10.0}, []),
            # At ratio 20 the raw granule counts miss (9.6x), but scaling both sides to rows (51x) fires.
            (
                "persons join fires once granules are scaled to rows",
                "plan_persons_join",
                {"persons_ratio": 20.0, "table_row_averages": {"sharded_events": 740.0, "person": 3955.0}},
                ["persons_join"],
            ),
            # Same granules and ratio, but averages that make the events side heavier keep it quiet.
            (
                "persons join stays quiet when rows do not clear the ratio",
                "plan_persons_join",
                {"persons_ratio": 20.0, "table_row_averages": {"sharded_events": 4000.0, "person": 740.0}},
                [],
            ),
            ("object storage read yields nothing", "plan_object_storage_read", {}, []),
            ("a replay list query reads no events", "plan_replay_list_in_subqueries", {}, []),
            # a subquery whose events read pruned nothing is flagged through the skip-step fallback
            (
                "a subquery with no event filter is flagged",
                "plan_event_filter_used",
                {"subqueries": ("plan_no_event_filter",)},
                ["no_event_filter"],
            ),
            # a subquery a skip index already pruned is not flagged
            (
                "a subquery a skip index pruned is not flagged",
                "plan_event_filter_used",
                {"subqueries": ("plan_skip_index_pruned",)},
                [],
            ),
        ]
    )
    def test_findings_per_gate(
        self, _name: str, outer: str | QueryPlan, kwargs: dict[str, object], expected_kinds: list[str]
    ) -> None:
        result = analyze_fixture(outer, **kwargs)  # type: ignore[arg-type]

        self.assertTrue(result.explain_ok)
        self.assertEqual(result.finding_kinds(), expected_kinds)

    def test_no_outer_plan_fails_closed(self) -> None:
        result = analyze(
            PlanSet(outer=None),
            QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5),
            query_kind="HogQLQuery",
            open_filters_placeholder=False,
        )

        self.assertFalse(result.explain_ok)
        self.assertEqual(result.findings, [])

    def test_open_filters_placeholder_sets_the_filters_reason(self) -> None:
        result = analyze_fixture("plan_no_date_bound", open_filters_placeholder=True)

        self.assertEqual([finding.reason for finding in result.findings], [QueryScanFindingReason.FILTERS])
        self.assertIn("No date range is set on this insight or dashboard", result.findings[0].message)

    def test_insight_kind_uses_the_insight_wording(self) -> None:
        result = analyze_fixture("plan_no_date_bound", query_kind="TrendsQuery")

        self.assertEqual(result.finding_kinds(), ["no_start_date"])
        self.assertIsNone(result.findings[0].reason)
        self.assertIn("This insight has no start date", result.findings[0].message)

    def test_a_negated_event_filter_is_flagged_with_its_reason(self) -> None:
        # `event != x` lists `event` in the key yet keeps most of the range, so the plan alone
        # cannot flag it; the combined outcome the job ships carries the tree's `negated` reason.
        result = analyze_fixture(
            "plan_event_filter_negated",
            range_granules=400_000,
            event_filter=EventFilterOutcome(classification="not_used", reason="negated"),
        )

        self.assertEqual(result.finding_kinds(), ["no_event_filter"])
        self.assertEqual(result.findings[0].reason, QueryScanFindingReason.NEGATED)
        self.assertIn("only excludes events", result.findings[0].message)

    def test_shares_are_the_read_over_the_denominators(self) -> None:
        result = analyze_fixture("plan_no_event_filter", team_granules=10_000_000, range_granules=1_000_000)

        assert result.range_share is not None and result.project_share is not None
        self.assertAlmostEqual(result.range_share, 0.329267, places=5)
        self.assertAlmostEqual(result.project_share, 0.0329267, places=6)

    def test_a_subquery_finding_names_the_subquery(self) -> None:
        result = analyze_fixture("plan_event_filter_used", subqueries=("plan_no_event_filter",))

        assert result.findings[0].evidence is not None
        self.assertIn("In subquery 1", result.findings[0].evidence)
