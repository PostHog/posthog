import dataclasses

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.cost.estimate import FilterEstimate, ScanEstimate, TableScanEstimate
from posthog.hogql.cost.explain import build_cost_plan
from posthog.hogql.index_eligibility import IndexEligibilityReport, PredicateIndexEligibility, PredicateIndexVerdict
from posthog.hogql.property_planner import PropertyScope, PropertySourceKind

EVENTS = TableScanEstimate(
    name="events",
    source="events",
    precision="measured",
    rows=41_000_000,
    days=30.0,
    events=("$pageview",),
    time_range="bounded",
    filters=(
        FilterEstimate(property_name="order_id", values=1, granules_read=0.0008),
        FilterEstimate(property_name="plan", values=1, granules_read=1.0),
        FilterEstimate(property_name="uncounted", values=1, granules_read=None),
    ),
)
ORDERS = TableScanEstimate(name="orders", source="warehouse", precision="size_only", rows=1_200_000, bytes=356_515_840)
PERSONS = TableScanEstimate(name="persons", source="clickhouse", precision="unknown")


def _predicate(
    name: str, scope: PropertyScope, verdict: PredicateIndexVerdict, **overrides
) -> PredicateIndexEligibility:
    return PredicateIndexEligibility(
        property_name=name,
        scope=scope,
        operator=ast.CompareOperationOp.Eq,
        source_kind=PropertySourceKind.MATERIALIZED_COLUMN,
        source_label="materialized column",
        column_name=None,
        semantic_type="String",
        physical_type="String",
        available_indexes=(),
        usable_indexes=(),
        verdict=verdict,
        blocker=None,
        message=f"message about {name}",
        fix=overrides.get("fix"),
        ai_fix_prompt=overrides.get("ai_fix_prompt"),
        start=None,
        end=None,
    )


class TestBuildCostPlan(SimpleTestCase):
    def test_no_estimate_means_no_plan(self):
        assert build_cost_plan(None, IndexEligibilityReport()) == ()

    def test_scans_come_in_from_order_with_their_filters_and_one_join_line(self):
        report = IndexEligibilityReport(
            predicates=(
                _predicate("order_id", PropertyScope.EVENT, PredicateIndexVerdict.INDEXED),
                _predicate("plan", PropertyScope.EVENT, PredicateIndexVerdict.INDEXED),
                _predicate("uncounted", PropertyScope.EVENT, PredicateIndexVerdict.INDEXED),
                _predicate("$browser", PropertyScope.EVENT, PredicateIndexVerdict.UNINDEXED_JSON, fix="Materialize it"),
                _predicate("tier", PropertyScope.PERSON, PredicateIndexVerdict.UNINDEXED_JSON),
            )
        )
        estimate = ScanEstimate(rows=42_200_000, upper_bound=True, tables=(EVENTS, ORDERS, PERSONS))

        steps = build_cost_plan(estimate, report)

        assert [(step.kind, step.table, step.message) for step in steps] == [
            ("scan", "events", "Scan events, about 41M rows (30 days)"),
            ("filter", "events", "Filter order_id = … skips over 99% of the scan"),
            ("filter", "events", "Filter plan = … skips almost nothing"),
            ("filter", "events", "Filter uncounted = … has an index, how much it skips is not estimated"),
            ("filter", "events", "Filter $browser = … reads every row"),
            ("scan", "orders", "Scan orders, up to 1.2M rows, 340.0 MB on disk"),
            ("scan", "persons", "Scan persons, size unknown"),
            ("filter", "persons", "Filter person.tier = … reads every row"),
            ("join", None, "Join 3 tables. Rows after the join are not estimated."),
        ]
        browser = steps[4]
        assert browser.detail == "message about $browser"
        assert browser.fix == "Materialize it"

    @parameterized.expand(
        [
            (
                "open_range_events",
                dataclasses.replace(EVENTS, time_range="open", days=365.0, events=()),
                "Scan events, about 41M rows (no date range, assuming a year)",
            ),
            ("hours", dataclasses.replace(EVENTS, days=1.5), "Scan events, about 41M rows (36 hours)"),
            (
                "size_only_rows_without_bytes",
                TableScanEstimate(name="persons", source="clickhouse", precision="size_only", rows=2_400_000),
                "Scan persons, up to 2.4M rows on disk",
            ),
        ]
    )
    def test_scan_lines(self, _name, table, expected):
        [step] = build_cost_plan(ScanEstimate(rows=table.rows or 0, upper_bound=False, tables=(table,)), None)

        assert step.message == expected

    def test_a_person_property_filters_the_events_scan_when_persons_is_not_scanned(self):
        report = IndexEligibilityReport(
            predicates=(_predicate("tier", PropertyScope.PERSON, PredicateIndexVerdict.BLOCKED),)
        )

        steps = build_cost_plan(ScanEstimate(rows=41_000_000, upper_bound=False, tables=(EVENTS,)), report)

        assert [(step.kind, step.table) for step in steps] == [("scan", "events"), ("filter", "events")]
        assert steps[1].message == "Filter person.tier = … index unused, reads every row"
