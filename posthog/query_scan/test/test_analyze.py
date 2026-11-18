from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.analyze import ExplainedPlan, PlanSet, QueryScanResult, RunFacts, analyze
from posthog.query_scan.event_filter import EventFilterOutcome
from posthog.query_scan.explain import QueryPlan, parse_query_plan
from posthog.query_scan.findings import finding_label
from posthog.query_scan.flag import QueryScanFlag, QueryScanMode
from posthog.query_scan.test.test_explain import events_read_node, load_plan
from posthog.query_scan.tree_facts import TreeFacts

_USABLE_EVENT_FILTER = EventFilterOutcome(classification="usable")
_END_DATE_ONLY = "(timestamp in (-Inf, 1800000000])"
# A start and an end date, in the two-clause form ClickHouse prints them in.
_BOTH_BOUNDS = "and((timestamp in (-Inf, 1800000000]), (timestamp in [1700000000, +Inf)))"


_EVENT_KEY = ["team_id", "toDate(timestamp)", "event"]

NO_START_DATE = "no_start_date"
NO_EVENT_FILTER = "no_event_filter"


def plan(name: str) -> QueryPlan:
    return parse_query_plan(load_plan(name))


def single_read_plan(condition: str) -> QueryPlan:
    return parse_query_plan([{"Plan": events_read_node(condition, ["timestamp"] if condition != "true" else [])}])


def join_plan(*reads: dict[str, object]) -> QueryPlan:
    return parse_query_plan([{"Plan": {"Node Type": "Join", "Plans": list(reads)}}])


# A join whose heaviest read pruned on nothing while its lighter read pruned on `event`: an
# unfiltered helper read beside a read that names events.
_HELPER_READ_PLAN = join_plan(
    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=5000),
    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=10, primary_keys=_EVENT_KEY),
)


def analyze_fixture(
    outer: str | QueryPlan,
    *,
    subqueries: tuple[str, ...] = (),
    subquery_range_granules: int | None = None,
    team_granules: int | None = None,
    range_granules: int | None = None,
    persons_ratio: float = 0.5,
    query_kind: str = "HogQLQuery",
    open_filters_placeholder: bool = False,
    event_filter: EventFilterOutcome | None = None,
    table_row_averages: dict[str, float] | None = None,
    all_time: bool = False,
    dashboard_all_time: bool = False,
    all_history_by_design: bool = False,
    all_events_by_design: bool = False,
    tree: TreeFacts | None = None,
) -> QueryScanResult:
    return analyze(
        PlanSet(
            outer=ExplainedPlan(
                plan=plan(outer) if isinstance(outer, str) else outer,
                range_granules=range_granules,
                event_filter=event_filter,
                tree=tree,
            ),
            subqueries=tuple(
                ExplainedPlan(plan=plan(name), range_granules=subquery_range_granules) for name in subqueries
            ),
            team_granules=team_granules,
        ),
        QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=persons_ratio),
        query_kind=query_kind,
        run=RunFacts(
            all_time=all_time,
            dashboard_all_time=dashboard_all_time,
            all_history_by_design=all_history_by_design,
            all_events_by_design=all_events_by_design,
            open_filters_placeholder=open_filters_placeholder,
        ),
        table_row_averages=table_row_averages,
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
            (
                "a small unbounded read is not flagged",
                join_plan(
                    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=5000),
                    events_read_node("true", [], selected_granules=10),
                ),
                {"event_filter": _USABLE_EVENT_FILTER, "team_granules": 10_000},
                [],
            ),
            (
                "an unbounded read over the start-date ratio is flagged",
                join_plan(
                    events_read_node(_BOTH_BOUNDS, ["timestamp"], selected_granules=5000),
                    events_read_node("true", [], selected_granules=10),
                ),
                {"event_filter": _USABLE_EVENT_FILTER, "team_granules": 500},
                ["no_start_date"],
            ),
            (
                "the largest unbounded read is the one sized, not the first",
                join_plan(
                    events_read_node("true", [], selected_granules=10),
                    events_read_node("true", [], selected_granules=5000),
                ),
                {"event_filter": _USABLE_EVENT_FILTER, "team_granules": 10_000},
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
                _HELPER_READ_PLAN,
                {"range_granules": 10_000},
                ["no_event_filter"],
            ),
            # An "All time" insight runs with a bound at the project's first event, so the plan alone
            # would stay quiet; the setting is what says no start date was chosen.
            (
                "all time insight is flagged despite the bound and whatever its size",
                "plan_event_filter_used",
                {"query_kind": "TrendsQuery", "all_time": True, "team_granules": 100_000_000_000},
                ["no_start_date"],
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
            # a subquery is gated on its share of its own date range, the way the outer query is
            (
                "a subquery that reads little of its date range is not flagged",
                "plan_event_filter_used",
                {"subqueries": ("plan_no_event_filter",), "subquery_range_granules": 40_000_000},
                [],
            ),
            # without its denominator, a subquery falls back to the skip steps, as the outer query does
            (
                "a subquery with no denominator and no pruning is flagged",
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

    @parameterized.expand(
        [
            ("no bound at all", "plan_no_date_bound", {}, [("no_start_date", True)]),
            (
                "a bound clickhouse could not use",
                "plan_no_date_bound",
                {"tree": TreeFacts(timestamp_bound=True)},
                [("no_start_date/bound_not_used", True)],
            ),
            (
                "a start date the plan never saw",
                "plan_no_date_bound",
                {"tree": TreeFacts(timestamp_bound=True, start_date_hidden_from_plan=True)},
                [],
            ),
            (
                "a first-ever computation in sql",
                "plan_no_date_bound",
                {"tree": TreeFacts(all_history=True, timestamp_bound=True)},
                [("no_start_date/by_design", False)],
            ),
            (
                "a first-time math on all time",
                "plan_event_filter_used",
                {"query_kind": "TrendsQuery", "all_time": True, "all_history_by_design": True},
                [("no_start_date/by_design", False)],
            ),
            (
                "all time chosen on the insight",
                "plan_event_filter_used",
                {"query_kind": "TrendsQuery", "all_time": True},
                [("no_start_date", True)],
            ),
            (
                "all time forced by the dashboard",
                "plan_event_filter_used",
                {"query_kind": "TrendsQuery", "all_time": True, "dashboard_all_time": True},
                [("no_start_date/dashboard_date_filter", True)],
            ),
            (
                "all time reaching sql through filters",
                "plan_no_date_bound",
                {"all_time": True, "open_filters_placeholder": True},
                [("no_start_date/insight_date_range", True)],
            ),
            (
                "the dashboard's all time reaching sql through filters",
                "plan_no_date_bound",
                {"all_time": True, "open_filters_placeholder": True, "dashboard_all_time": True},
                [("no_start_date/dashboard_date_filter", True)],
            ),
            (
                "a read inside a saved view",
                "plan_no_date_bound",
                {"tree": TreeFacts(view_name="v_active")},
                [("no_start_date/view", True)],
            ),
            (
                "sql with no event condition at all",
                "plan_no_event_filter",
                {"range_granules": 1_000_000},
                [("no_event_filter", True)],
            ),
            (
                "an insight on all events",
                "plan_no_event_filter",
                {"range_granules": 1_000_000, "query_kind": "TrendsQuery"},
                [("no_event_filter", False)],
            ),
            (
                "a shape that reads every event of all history is not believed",
                single_read_plan("true"),
                {"tree": TreeFacts(all_history=True, counts_any_event=True)},
                [("no_start_date", True), ("no_event_filter", True)],
            ),
            (
                "an insight's settings are believed over every event of all history",
                single_read_plan("true"),
                {"query_kind": "TrendsQuery", "all_time": True, "all_history_by_design": True},
                [("no_start_date/by_design", False), ("no_event_filter", False)],
            ),
            (
                "a property filter standing in for an event name",
                "plan_no_event_filter",
                {"range_granules": 1_000_000, "tree": TreeFacts(property_filter=True)},
                [("no_event_filter/property_filter", True)],
            ),
            (
                "a property filter on an all events insight",
                "plan_no_event_filter",
                {"range_granules": 1_000_000, "query_kind": "TrendsQuery", "tree": TreeFacts(property_filter=True)},
                [("no_event_filter/property_filter", True)],
            ),
            (
                "grouping by event beside a property filter",
                "plan_no_event_filter",
                {"range_granules": 1_000_000, "tree": TreeFacts(groups_by_event=True, property_filter=True)},
                [("no_event_filter/by_design", False)],
            ),
            (
                "counting distinct people over any event",
                "plan_no_event_filter",
                {"range_granules": 1_000_000, "tree": TreeFacts(counts_any_event=True)},
                [("no_event_filter/by_design", False)],
            ),
            (
                "counting distinct people with a property filter",
                "plan_no_event_filter",
                {"range_granules": 1_000_000, "tree": TreeFacts(counts_any_event=True, property_filter=True)},
                [("no_event_filter/property_filter", True)],
            ),
            (
                "an active-user math on all events",
                "plan_no_event_filter",
                {"range_granules": 1_000_000, "query_kind": "TrendsQuery", "all_events_by_design": True},
                [("no_event_filter/by_design", False)],
            ),
            (
                "an unfiltered helper read in sql",
                _HELPER_READ_PLAN,
                {"range_granules": 10_000, "tree": TreeFacts(counts_any_event=True)},
                [("no_event_filter/helper_read", True)],
            ),
            (
                "an unfiltered helper read in an insight",
                _HELPER_READ_PLAN,
                {"range_granules": 10_000, "query_kind": "TrendsQuery"},
                [("no_event_filter", False)],
            ),
            (
                "an unfiltered subquery is worded like an unfiltered outer query",
                "plan_event_filter_used",
                {"subqueries": ("plan_no_event_filter",)},
                [("no_event_filter/subquery", True)],
            ),
            (
                "a negated event filter",
                "plan_event_filter_negated",
                {
                    "range_granules": 400_000,
                    "event_filter": EventFilterOutcome(classification="not_used", reason="negated"),
                },
                [("no_event_filter/negated", True)],
            ),
            (
                "an event filter inside an or",
                "plan_no_event_filter",
                {
                    "range_granules": 1_000_000,
                    "event_filter": EventFilterOutcome(classification="not_used", reason="in_or"),
                },
                [("no_event_filter/in_or", True)],
            ),
        ]
    )
    def test_labels_and_actionability(
        self,
        _name: str,
        outer: str | QueryPlan,
        kwargs: dict[str, object],
        expected: list[tuple[str, bool]],
    ) -> None:
        result = analyze_fixture(outer, **kwargs)  # type: ignore[arg-type]

        self.assertEqual([(finding_label(finding), finding.actionable) for finding in result.findings], expected)

    def test_no_outer_plan_fails_closed(self) -> None:
        result = analyze(
            PlanSet(outer=None),
            QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5),
            query_kind="HogQLQuery",
            run=RunFacts(),
        )

        self.assertFalse(result.explain_ok)
        self.assertEqual(result.findings, [])

    def test_open_filters_placeholder_puts_the_fix_on_the_insight(self) -> None:
        result = analyze_fixture("plan_no_date_bound", open_filters_placeholder=True)

        self.assertEqual(result.finding_labels(), ["no_start_date/insight_date_range"])
        self.assertIn("The date range on this insight or dashboard has no start date", result.findings[0].message)

    def test_insight_kind_uses_the_insight_wording(self) -> None:
        result = analyze_fixture("plan_no_date_bound", query_kind="TrendsQuery")

        self.assertEqual(result.finding_kinds(), ["no_start_date"])
        self.assertIsNone(result.findings[0].cause)
        self.assertIn("This insight has no start date", result.findings[0].message)

    @parameterized.expand(
        [
            (
                "the dashboard's date filter",
                "plan_event_filter_used",
                {"query_kind": "TrendsQuery", "all_time": True, "dashboard_all_time": True},
                "The dashboard's date filter is set to All time",
            ),
            (
                "the saved view the read sits in",
                "plan_no_date_bound",
                {"tree": TreeFacts(view_name="v_active")},
                "The view `v_active` inside this query has no start date",
            ),
            (
                "the subquery the read sits in",
                "plan_event_filter_used",
                {"subqueries": ("plan_no_date_bound",)},
                "Subquery 1 of this query has no start date",
            ),
            (
                "the subquery, not the insight's date range, when the query takes its dates from filters",
                "plan_event_filter_used",
                {"subqueries": ("plan_no_date_bound",), "open_filters_placeholder": True},
                "Subquery 1 of this query has no start date",
            ),
        ]
    )
    def test_the_headline_names_the_cause(
        self, _name: str, outer: str, kwargs: dict[str, object], expected_in_message: str
    ) -> None:
        result = analyze_fixture(outer, **kwargs)  # type: ignore[arg-type]

        self.assertEqual(result.finding_kinds(), ["no_start_date"])
        self.assertIn(expected_in_message, result.findings[0].message)

    def test_shares_are_the_read_over_the_denominators(self) -> None:
        result = analyze_fixture("plan_no_event_filter", team_granules=10_000_000, range_granules=1_000_000)

        assert result.range_share is not None and result.project_share is not None
        self.assertAlmostEqual(result.range_share, 0.329267, places=5)
        self.assertAlmostEqual(result.project_share, 0.0329267, places=6)

    def test_a_filter_the_plan_never_saw_gets_no_share_and_no_finding(self) -> None:
        result = analyze_fixture(
            "plan_no_event_filter",
            team_granules=10_000_000,
            range_granules=1_000_000,
            event_filter=EventFilterOutcome(classification="usable", hidden_from_plan=True),
        )

        self.assertEqual((result.range_share, result.project_share, result.findings), (None, None, []))

    def test_a_subquery_finding_names_the_subquery(self) -> None:
        result = analyze_fixture("plan_event_filter_used", subqueries=("plan_no_event_filter",))

        assert result.findings[0].evidence is not None
        self.assertIn("In subquery 1", result.findings[0].evidence)
        self.assertIn("Subquery 1 of this query", result.findings[0].message)
