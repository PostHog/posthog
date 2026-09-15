from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.emitter_version import describe_emitter_version_shift
from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context

from products.event_definitions.backend.models.event_property import EventProperty

JUDGED = "report judged"


@parameterized.expand([("no_triggered_dates", []), ("unparseable_dates", ["last thursday"])])
def test_says_nothing_without_a_window_to_measure(_name: str, triggered_dates: list[str]) -> None:
    assert describe_emitter_version_shift(team=MagicMock(), event=JUDGED, triggered_dates=triggered_dates) == ""


@patch("posthog.temporal.ai.anomaly_investigation.emitter_version.execute_hogql_query")
def test_says_nothing_rather_than_failing_the_investigation(mock_query: MagicMock) -> None:
    mock_query.side_effect = RuntimeError("ClickHouse is down")

    assert describe_emitter_version_shift(team=MagicMock(), event=JUDGED, triggered_dates=["2026-09-14"]) == ""


def test_context_carries_the_emitter_version_block() -> None:
    context = build_anomaly_context(
        alert_name="Noise rate climbed",
        metric_description="Report noise rate",
        detector_type="ensemble",
        triggered_dates=["2026-09-14"],
        triggered_metadata=None,
        calculated_value=0.253,
        interval="day",
        metric_definition="Metric definition — ...",
        emitter_version='Emitter version — how the version properties on event "report judged" moved',
    )

    assert 'Emitter version — how the version properties on event "report judged" moved' in context
    assert "Submit the final InvestigationReport" in context


class TestEmitterVersionAgainstClickHouse(ClickhouseTestMixin, BaseTest):
    def _judge(self, day: str, judge_version: str, count: int, *, body_version: str = "4") -> None:
        for index in range(count):
            _create_event(
                team=self.team,
                event=JUDGED,
                distinct_id=f"judge-{index}",
                timestamp=f"{day}T12:00:00Z",
                properties={"judge_version": judge_version, "output_checks_version": body_version},
            )

    def _record_taxonomy(self, *properties: str) -> None:
        for name in properties:
            EventProperty.objects.create(team=self.team, event=JUDGED, property=name)

    def test_reports_the_version_that_took_over_the_window(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["judge-0"])
        self._record_taxonomy("judge_version", "output_checks_version")
        for day in ("2026-09-01", "2026-09-05", "2026-09-10"):
            self._judge(day, "17", 10)
        self._judge("2026-09-14", "23", 10)
        flush_persons_and_events()

        described = describe_emitter_version_shift(team=self.team, event=JUDGED, triggered_dates=["2026-09-14"])

        assert "`judge_version` changed mix: 23 went 0% -> 100% of events" in described
        assert "17 went 100% -> 0% of events" in described
        # The version the judge writes into its own payload never moved, which is how a
        # judge change hides from a reader who trusts that field.
        assert "output_checks_version" not in described.split("How to read this block:")[0]

    def test_rules_the_producer_out_when_the_mix_held(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["judge-0"])
        self._record_taxonomy("judge_version")
        for day in ("2026-09-01", "2026-09-05", "2026-09-10", "2026-09-14"):
            self._judge(day, "17", 10)
        flush_persons_and_events()

        described = describe_emitter_version_shift(team=self.team, event=JUDGED, triggered_dates=["2026-09-14"])

        assert "No version boundary: `judge_version` held the same mix across both periods." in described

    def test_says_nothing_when_the_event_records_no_version_property(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["judge-0"])
        self._record_taxonomy("severity")
        self._judge("2026-09-14", "23", 10)
        flush_persons_and_events()

        assert describe_emitter_version_shift(team=self.team, event=JUDGED, triggered_dates=["2026-09-14"]) == ""
