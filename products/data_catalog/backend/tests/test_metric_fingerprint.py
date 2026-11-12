from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from unittest.mock import PropertyMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.data_catalog.backend.facade.enums import HOGQL_DEFINITION_KIND, MetricStatus, ShapeOutcome
from products.data_catalog.backend.logic.measure_fingerprint import extract_measures
from products.data_catalog.backend.logic.metric_fingerprint import (
    CatalogIndex,
    CatalogMeasure,
    definition_to_hogql,
    fingerprint_metric,
)
from products.data_catalog.backend.models import Metric

SIGNUPS_AND_SIGNERS = "SELECT count(), uniq(person_id) FROM events WHERE event = 'signup'"
APPROVED_ID = UUID("00000000-0000-0000-0000-000000000001")
PROPOSED_ID = UUID("00000000-0000-0000-0000-000000000002")


def _catalog(*metrics: tuple[UUID, MetricStatus, str]) -> CatalogIndex:
    return CatalogIndex(
        CatalogMeasure(
            metric_id=metric_id,
            status=status,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            fingerprint=fingerprint,
        )
        for metric_id, status, query in metrics
        for fingerprint in extract_measures(query)
    )


def _only_measure(query: str) -> Any:
    measures = extract_measures(query)
    assert len(measures) == 1, query
    return measures[0]


class TestCatalogIndex(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "second_measure_of_a_metric",
                "SELECT uniq(person_id) FROM events WHERE event = 'signup' GROUP BY toDate(timestamp)",
                ShapeOutcome.COVERED,
                APPROVED_ID,
            ),
            (
                "extra_filter",
                "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'",
                ShapeOutcome.SLICE,
                APPROVED_ID,
            ),
            (
                "different_aggregate",
                "SELECT sum(properties.amount) FROM events WHERE event = 'signup'",
                ShapeOutcome.UNCOVERED,
                None,
            ),
            (
                "missing_filter",
                "SELECT count() FROM events",
                ShapeOutcome.UNCOVERED,
                None,
            ),
        ]
    )
    def test_classify(self, _name: str, query: str, outcome: ShapeOutcome, metric_id: UUID | None) -> None:
        match = _catalog((APPROVED_ID, MetricStatus.APPROVED, SIGNUPS_AND_SIGNERS)).classify(_only_measure(query))

        assert (match.outcome, match.metric_id) == (outcome, metric_id)

    def test_approved_metric_wins_over_proposed_one(self) -> None:
        catalog = _catalog(
            (PROPOSED_ID, MetricStatus.PROPOSED, "SELECT count() FROM events WHERE event = 'signup'"),
            (APPROVED_ID, MetricStatus.APPROVED, SIGNUPS_AND_SIGNERS),
        )

        match = catalog.classify(_only_measure("SELECT count() FROM events WHERE event = 'signup'"))

        assert match.metric_id == APPROVED_ID


class TestMeasureOrdering(SimpleTestCase):
    @parameterized.expand(
        [
            ("sides_of_equals", "event = 'a'", "'a' = event"),
            ("sides_of_not_equals", "event != 'a'", "'a' != event"),
            ("or_order", "event = 'a' OR event = 'b'", "event = 'b' OR event = 'a'"),
            ("nested_or", "(a = 1 OR b = 2) OR c = 3", "a = 1 OR (c = 3 OR b = 2)"),
            ("repeated_or_operand", "a = 1 OR a = 1 OR b = 2", "a = 1 OR b = 2"),
            ("in_list", "event IN ('a', 'b')", "event IN ('b', 'a')"),
            ("not_in_list", "event NOT IN ('a', 'b')", "event NOT IN ('b', 'a')"),
            ("and_order_inside_or", "(a = 1 AND b = 2) OR c = 3", "(b = 2 AND a = 1) OR c = 3"),
        ]
    )
    def test_order_does_not_change_a_filter(self, _name: str, first: str, second: str) -> None:
        template = "SELECT count() FROM events WHERE {}"
        assert extract_measures(template.format(first))[0].digest == extract_measures(template.format(second))[0].digest

    def test_order_does_not_change_an_aggregate_condition(self) -> None:
        first = extract_measures("SELECT countIf(event = 'a' AND x = 1) FROM events")[0]
        second = extract_measures("SELECT countIf(x = 1 AND 'a' = event) FROM events")[0]

        assert first.digest == second.digest

    @parameterized.expand(
        [
            ("subtraction", "SELECT sum(a - b) FROM t", "SELECT sum(b - a) FROM t"),
            ("division", "SELECT sum(a / b) FROM t", "SELECT sum(b / a) FROM t"),
            ("greater_than", "SELECT count() FROM t WHERE a > b", "SELECT count() FROM t WHERE b > a"),
            ("function_arguments", "SELECT sum(if(a = 1, x, y)) FROM t", "SELECT sum(if(a = 1, y, x)) FROM t"),
            ("different_value", "SELECT count() FROM t WHERE a = 1", "SELECT count() FROM t WHERE a = 2"),
            ("in_and_not_in", "SELECT count() FROM t WHERE a IN (1, 2)", "SELECT count() FROM t WHERE a NOT IN (1, 2)"),
            (
                "and_against_or",
                "SELECT count() FROM t WHERE a = 1 AND b = 2",
                "SELECT count() FROM t WHERE a = 1 OR b = 2",
            ),
        ]
    )
    def test_order_that_changes_the_result_keeps_measures_apart(self, _name: str, first: str, second: str) -> None:
        assert extract_measures(first)[0].digest != extract_measures(second)[0].digest

    def test_a_filter_still_reads_as_written(self) -> None:
        assert extract_measures("SELECT count() FROM events WHERE 'a' = event")[0].describe() == (
            "count() on events where event = 'a'"
        )


class TestDefinitionToHogQL(SimpleTestCase):
    team = Team(id=1, project_id=1, test_account_filters=[])

    def setUp(self) -> None:
        # The real property reads an instance setting from the database.
        patcher = patch.object(Team, "aggregate_users_by_distinct_id", new_callable=PropertyMock, return_value=False)
        self.aggregate_by_distinct_id = patcher.start()
        self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            (
                "trends_total_with_property_filter",
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "signup",
                            "math": "total",
                            "properties": [{"key": "plan", "value": "pro", "operator": "exact", "type": "event"}],
                        }
                    ],
                    "breakdownFilter": {"breakdown": "$browser"},
                },
                "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro' GROUP BY day",
            ),
            (
                "events_node_dau",
                {"kind": "EventsNode", "event": "signup", "math": "dau"},
                "SELECT uniq(person_id) FROM events WHERE event = 'signup'",
            ),
            (
                "events_node_p90",
                {"kind": "EventsNode", "event": "checkout", "math": "p90", "math_property": "amount"},
                "SELECT quantile(0.9)(properties.amount) FROM events WHERE event = 'checkout'",
            ),
            (
                "person_property_math",
                {
                    "kind": "EventsNode",
                    "event": "checkout",
                    "math": "sum",
                    "math_property": "ltv",
                    "math_property_type": "person_properties",
                },
                "SELECT sum(person.properties.ltv) FROM events WHERE event = 'checkout'",
            ),
            (
                "math_multiplier",
                {
                    "kind": "EventsNode",
                    "event": "checkout",
                    "math": "sum",
                    "math_property": "cents",
                    "math_multiplier": 0.01,
                },
                "SELECT sum(properties.cents * 0.01) FROM events WHERE event = 'checkout'",
            ),
        ]
    )
    def test_converted_definition_matches_the_hand_written_query(
        self, _name: str, definition: dict[str, Any], hand_written: str
    ) -> None:
        converted = definition_to_hogql(definition, self.team)

        assert converted is not None
        assert _only_measure(converted).digest == _only_measure(hand_written).digest

    @parameterized.expand(
        [
            (
                "two_series",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "a"}, {"kind": "EventsNode", "event": "b"}],
                },
            ),
            ("funnel", {"kind": "FunnelsQuery", "series": [{"kind": "EventsNode", "event": "a"}]}),
            ("property_math_without_property", {"kind": "EventsNode", "event": "a", "math": "sum"}),
            (
                "formula",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "a"}],
                    "trendsFilter": {"formula": "A * 2"},
                },
            ),
            (
                "session_property_math",
                {
                    "kind": "EventsNode",
                    "event": "a",
                    "math": "avg",
                    "math_property": "$is_bounce",
                    "math_property_type": "session_properties",
                },
            ),
            (
                "revenue_converted_to_the_team_currency",
                {
                    "kind": "EventsNode",
                    "event": "purchase",
                    "math": "sum",
                    "math_property": "amount",
                    "math_property_revenue_currency": {"static": "EUR"},
                },
            ),
        ]
    )
    def test_definitions_no_single_aggregate_captures_convert_to_none(
        self, _name: str, definition: dict[str, Any]
    ) -> None:
        assert definition_to_hogql(definition, self.team) is None

    def test_dau_counts_distinct_ids_when_the_team_aggregates_by_distinct_id(self) -> None:
        self.aggregate_by_distinct_id.return_value = True

        converted = definition_to_hogql({"kind": "EventsNode", "event": "signup", "math": "dau"}, self.team)

        assert converted is not None
        assert _only_measure(converted).aggregate == "uniq(distinct_id)"

    @parameterized.expand(
        [
            (
                "hogql_values_bind_as_placeholders",
                {
                    "kind": HOGQL_DEFINITION_KIND,
                    "query": "SELECT count() FROM events WHERE event = {event}",
                    "values": {"event": "signup"},
                },
                "SELECT count() FROM events WHERE event = 'signup'",
            ),
            (
                "conversion_error_leaves_the_metric_unmeasured",
                {"kind": "EventsNode", "event": "a", "math": "hogql", "math_hogql": "count("},
                None,
            ),
        ]
    )
    def test_fingerprint_metric(self, _name: str, definition: dict[str, Any], expected_query: str | None) -> None:
        fingerprints = fingerprint_metric(Metric(team_id=1, definition=definition), self.team)

        expected = [] if expected_query is None else [_only_measure(expected_query)]
        assert [f.digest for f in fingerprints] == [f.digest for f in expected]

    @parameterized.expand([("bare_exception", Exception("join was deleted")), ("recursion", RecursionError())])
    def test_any_conversion_error_leaves_the_metric_unmeasured(self, _name: str, error: BaseException) -> None:
        with patch("products.data_catalog.backend.logic.metric_fingerprint.definition_to_hogql", side_effect=error):
            assert (
                fingerprint_metric(Metric(team_id=1, definition={"kind": "EventsNode", "event": "a"}), self.team) == []
            )
