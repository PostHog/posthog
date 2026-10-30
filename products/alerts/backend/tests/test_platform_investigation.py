from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema_enums import AlertCalculationInterval
from posthog.temporal.alerts.investigation import MAX_INVESTIGATIONS_PER_EPISODE, InvestigationDecision

from products.alerts.backend.models.alert import AlertConfiguration, InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_investigation import InvestigationClaim, claim_investigation, decide_investigation
from products.product_analytics.backend.facade.models import Insight

NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)
EPISODE = NOW - timedelta(hours=6)


class TestPlatformInvestigation(BaseTest):
    alert: AlertConfiguration
    configuration_id: UUID

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.alert = AlertConfiguration.objects.create(
            team=cls.team,
            insight=Insight.objects.create(team=cls.team, name="Signups"),
            name="Signups dropped",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            calculation_interval=AlertCalculationInterval.HOURLY,
        )
        cls.configuration_id = uuid4()

    def _investigation(
        self,
        *,
        at: datetime,
        status: str = InvestigationStatus.DONE,
        verdict: str | None = None,
        episode_started_at: datetime | None = EPISODE,
        key: str | None = None,
    ) -> None:
        with time_machine.travel(at, tick=False):
            InsightAlertInvestigation.objects.for_team(self.team.id).create(
                team=self.team,
                alert_configuration=self.alert,
                configuration_id=self.configuration_id,
                evaluation_key=key or f"slot:{at.isoformat()}",
                episode_started_at=episode_started_at,
                kind=InsightAlertInvestigation.Kind.AGENT,
                status=status,
                verdict=verdict,
            )

    def _decide(self, *, firing: bool = True, key: str = "slot:now") -> InvestigationDecision:
        return decide_investigation(
            self.alert,
            firing=firing,
            configuration_id=self.configuration_id,
            evaluation_key=key,
            episode_started_at=EPISODE,
        )

    def _claim(self, key: str = "slot:now") -> InvestigationClaim:
        with time_machine.travel(NOW, tick=False):
            return claim_investigation(
                self.alert,
                configuration_id=self.configuration_id,
                evaluation_key=key,
                episode_started_at=EPISODE,
                kind=InsightAlertInvestigation.Kind.AGENT,
                evaluated={"value": 3.0},
            )

    @parameterized.expand([("first", 0, True), ("last", MAX_INVESTIGATIONS_PER_EPISODE - 1, True), ("spent", 3, False)])
    def test_a_firing_investigates_until_its_budget_is_spent(self, _name: str, started: int, expected: bool) -> None:
        for index in range(started):
            self._investigation(at=EPISODE + timedelta(hours=index), verdict="false_positive")

        decision = self._decide()

        assert decision.should_investigate is expected
        assert decision.previous_verdict == ("false_positive" if started else None)

    def test_only_started_investigations_of_this_firing_spend_its_budget(self) -> None:
        for index in range(MAX_INVESTIGATIONS_PER_EPISODE):
            self._investigation(at=EPISODE + timedelta(hours=index), status=InvestigationStatus.SKIPPED)
            self._investigation(
                at=EPISODE - timedelta(days=1, hours=index),
                episode_started_at=EPISODE - timedelta(days=1),
                verdict="true_positive",
            )
        # A retry repeats the decision after its own claim wrote a row, which must not count against it.
        self._investigation(at=NOW, status=InvestigationStatus.PENDING, verdict="true_positive", key="slot:now")

        decision = self._decide()

        assert decision.should_investigate is True
        assert decision.previous_verdict is None

    def test_a_check_that_is_not_firing_never_investigates(self) -> None:
        assert self._decide(firing=False).should_investigate is False

    @parameterized.expand(
        [
            ("nothing recent", None, timedelta(0), AlertCalculationInterval.HOURLY, True),
            (
                "done inside the cooldown",
                InvestigationStatus.DONE,
                timedelta(minutes=10),
                AlertCalculationInterval.HOURLY,
                False,
            ),
            (
                "done after the cooldown",
                InvestigationStatus.DONE,
                timedelta(hours=2),
                AlertCalculationInterval.HOURLY,
                True,
            ),
            # Half an hour is far past a real-time alert's cooldown, and the agent is still running.
            (
                "in flight past the cooldown",
                InvestigationStatus.RUNNING,
                timedelta(minutes=30),
                AlertCalculationInterval.REAL_TIME,
                False,
            ),
        ]
    )
    def test_a_claim_is_refused_by_an_investigation_in_flight_or_inside_the_cooldown(
        self, _name: str, earlier: str | None, age: timedelta, interval: str, claimed: bool
    ) -> None:
        self.alert.calculation_interval = interval
        if earlier is not None:
            self._investigation(at=NOW - age, status=earlier)

        claim = self._claim()

        assert claim.claimed is claimed
        row = InsightAlertInvestigation.objects.for_team(self.team.id).get(id=claim.investigation_id)
        assert row.status == (InvestigationStatus.PENDING if claimed else InvestigationStatus.SKIPPED)

    @parameterized.expand([("claimed", None, True), ("refused", InvestigationStatus.RUNNING, False)])
    def test_a_repeated_claim_returns_the_first_answer(self, _name: str, earlier: str | None, claimed: bool) -> None:
        if earlier is not None:
            self._investigation(at=NOW - timedelta(minutes=5), status=earlier)
        first = self._claim()
        InsightAlertInvestigation.objects.for_team(self.team.id).exclude(id=first.investigation_id).delete()

        assert self._claim() == first
        assert first.claimed is claimed
