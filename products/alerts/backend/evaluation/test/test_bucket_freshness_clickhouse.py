import time_machine
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events

from posthog.test.persons import create_person

from products.alerts.backend.evaluation.dispatcher import check_alert_for_insight
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.product_analytics.backend.facade.models import Insight


class TestHourlyAlertScoresItsOwnWindow(APIBaseTest, ClickhouseDestroyTablesMixin):
    def _hour_of_events(self, hour: str, starts: int, finishes: int) -> None:
        for i in range(starts):
            create_person(team_id=self.team.pk, distinct_ids=[f"{hour}_{i}"])
            _create_event(team=self.team, event="step_a", distinct_id=f"{hour}_{i}", timestamp=f"{hour}:10:00Z")
        for i in range(finishes):
            _create_event(team=self.team, event="step_b", distinct_id=f"{hour}_{i}", timestamp=f"{hour}:20:00Z")

    def test_consecutive_hourly_checks_do_not_reuse_the_previous_window(self) -> None:
        self.team.timezone = "UTC"
        self.team.save()

        self._hour_of_events("2026-10-28T20", starts=10, finishes=6)
        self._hour_of_events("2026-10-28T21", starts=10, finishes=9)
        flush_persons_and_events()

        insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "FunnelsQuery",
                "interval": "hour",
                "dateRange": {"date_from": "-1h"},
                "series": [
                    {"kind": "EventsNode", "event": "step_a"},
                    {"kind": "EventsNode", "event": "step_b"},
                ],
            },
        )
        alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            name="hourly funnel",
            condition={"type": "absolute_value"},
            config={"type": "FunnelsAlertConfig", "metric": "conversion_from_start", "funnel_step": None},
            calculation_interval="hourly",
            threshold=Threshold.objects.create(
                team=self.team, insight=insight, name="t", configuration={"type": "absolute", "bounds": {"lower": 0}}
            ),
        )

        with time_machine.travel("2026-10-28T21:01:20Z", tick=False):
            first = check_alert_for_insight(alert)
        with time_machine.travel("2026-10-28T22:01:13Z", tick=False):
            second = check_alert_for_insight(alert)

        assert first.value == 75.0
        assert second.value == 90.0
