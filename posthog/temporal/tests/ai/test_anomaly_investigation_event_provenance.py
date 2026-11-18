from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.event_provenance import alerted_series_event, describe_event_provenance
from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context

# A bare hourly count of an opaquely named custom event — the shape whose name tells the
# agent nothing about whether a person or a background job emits it.
BARE_EVENT_COUNT = {
    "kind": "InsightVizNode",
    "source": {
        "kind": "TrendsQuery",
        "interval": "hour",
        "series": [{"kind": "EventsNode", "event": "recording analyzed", "math": "total"}],
    },
}

TWO_SERIES = {
    "kind": "TrendsQuery",
    "series": [
        {"kind": "EventsNode", "event": "$pageview", "math": "dau"},
        {"kind": "EventsNode", "event": "recording analyzed", "math": "total"},
    ],
}


@parameterized.expand(
    [
        ("through_the_insight_viz_wrapper", BARE_EVENT_COUNT, 0),
        ("for_the_alerted_series_not_series_zero", TWO_SERIES, 1),
    ]
)
def test_reads_the_event_the_alerted_series_counts(_name: str, query: Any, series_index: int) -> None:
    assert alerted_series_event(query, series_index=series_index) == "recording analyzed"


@parameterized.expand(
    [
        ("action", {"kind": "TrendsQuery", "series": [{"kind": "ActionsNode", "id": 12, "name": "Signed up"}]}, 0),
        ("all_events", {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": None}]}, 0),
        ("sql_insight", {"kind": "HogQLQuery", "query": "SELECT count() FROM events"}, 0),
        ("index_out_of_range", {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}, 1),
        ("unreadable", "not a query", 0),
    ]
)
def test_returns_no_event_when_the_series_does_not_name_one(_name: str, query: Any, series_index: int) -> None:
    assert alerted_series_event(query, series_index=series_index) is None


@parameterized.expand([("query_failed", RuntimeError("ClickHouse is down")), ("no_rows", None)])
@patch("posthog.temporal.ai.anomaly_investigation.event_provenance.execute_hogql_query")
def test_says_nothing_rather_than_failing_the_investigation(
    _name: str, failure: Exception | None, mock_query: MagicMock
) -> None:
    if failure is not None:
        mock_query.side_effect = failure
    else:
        response = MagicMock()
        response.results = []
        mock_query.return_value = response

    assert describe_event_provenance(team=MagicMock(), event="recording analyzed") == ""


def test_context_carries_the_provenance_block() -> None:
    context = build_anomaly_context(
        alert_name="Headline metric dipped",
        metric_description="Recording AI summaries",
        detector_type="zscore",
        triggered_dates=["2026-08-30"],
        triggered_metadata=None,
        calculated_value=3896.0,
        interval="hour",
        metric_definition="Metric definition — ...",
        event_provenance='Event provenance — who emits event "recording analyzed"',
    )

    assert 'Event provenance — who emits event "recording analyzed"' in context
    assert "Submit the final InvestigationReport" in context


class TestEventProvenanceAgainstClickHouse(ClickhouseTestMixin, BaseTest):
    def test_counts_the_actors_that_emit_the_event(self) -> None:
        for index in range(3):
            distinct_id = f"person-{index}"
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            for _ in range(2):
                _create_event(
                    team=self.team,
                    event="recording analyzed",
                    distinct_id=distinct_id,
                    properties={"$lib": "posthog-python"},
                )
        _create_person(team_id=self.team.pk, distinct_ids=["other"])
        _create_event(team=self.team, event="recording viewed", distinct_id="other", properties={"$lib": "web"})
        flush_persons_and_events()

        described = describe_event_provenance(team=self.team, event="recording analyzed")

        assert "`$lib` posthog-python: 6 events from 3 distinct actors (2.0 events per actor)" in described
        assert "recording viewed" not in described
