from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.data_catalog.backend.facade.enums import MetricStatus, ShapeOutcome
from products.data_catalog.backend.logic.measure_fingerprint import extract_measures
from products.data_catalog.backend.logic.metric_fingerprint import CatalogIndex, CatalogMeasure, definition_to_hogql

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

        assert (match.metric_id, match.metric_status) == (APPROVED_ID, MetricStatus.APPROVED)


class TestDefinitionToHogQL(SimpleTestCase):
    team = Team(id=1, project_id=1, test_account_filters=[])

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
        ]
    )
    def test_definitions_no_single_aggregate_captures_convert_to_none(
        self, _name: str, definition: dict[str, Any]
    ) -> None:
        assert definition_to_hogql(definition, self.team) is None
