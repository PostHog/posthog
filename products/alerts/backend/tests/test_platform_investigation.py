from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval
from posthog.temporal.alerts.investigation import MAX_INVESTIGATIONS_PER_EPISODE, InvestigationDecision

from products.alerts.backend.investigation_release import RUNNING_HOLD, InvestigationRelease, finish_investigation
from products.alerts.backend.models.alert import AlertConfiguration, InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_investigation import InvestigationClaim, claim_investigation, decide_investigation
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest, HeldDeliveryAddress, SourceKind
from products.alerts_platform.backend.facade.enums import HoldRelease, HoldReleasedBy
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


class TestFinishInvestigation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=Insight.objects.create(team=self.team, name="Signups"),
            name="Signups dropped",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            investigation_gates_notifications=True,
        )
        with team_scope(self.team.id):
            self.configuration = platform_testing.create_configuration(
                team_id=self.team.id,
                name="Signups dropped",
                source_kind=SourceKind.INSIGHT,
                check_interval_minutes=60,
                next_check_at=NOW,
            )
        self.address = HeldDeliveryAddress(
            team_id=self.team.id, configuration_id=str(self.configuration.id), evaluation_key="slot:now"
        )
        self.request = AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=self.team.id,
            configuration_id=str(self.configuration.id),
            evaluation_key="slot:now",
            destination_alert_id=str(self.alert.id),
            event_ids_by_kind={"firing": "$insight_alert_firing"},
            owned_by_platform=True,
        )

    def _row(self, key: str, *, status: str, verdict: str | None = None) -> InsightAlertInvestigation:
        return InsightAlertInvestigation.objects.for_team(self.team.id).create(
            team=self.team,
            alert_configuration=self.alert,
            configuration_id=self.configuration.id,
            evaluation_key=key,
            episode_started_at=EPISODE,
            kind=InsightAlertInvestigation.Kind.AGENT,
            status=status,
            verdict=verdict,
        )

    def _hold(self, *, released: HoldRelease | None = None) -> None:
        platform_testing.hold_delivery(
            self.request,
            held_at=NOW,
            release_after=NOW + RUNNING_HOLD,
            released=(released, HoldReleasedBy.SAFETY_NET) if released else None,
        )

    def _finish(self, investigation: InsightAlertInvestigation, verdict: str) -> InvestigationRelease:
        return finish_investigation(self.alert, investigation, verdict=verdict, summary="Found it.", notebook_id=None)

    @parameterized.expand(
        [
            ("a true positive sends", "true_positive", True, HoldRelease.SEND),
            ("a false positive suppresses", "false_positive", True, HoldRelease.SUPPRESS),
            ("a disabled alert suppresses", "true_positive", False, HoldRelease.SUPPRESS),
        ]
    )
    def test_a_verdict_releases_the_held_firing(
        self, _name: str, verdict: str, enabled: bool, action: HoldRelease
    ) -> None:
        self.alert.enabled = enabled
        self.alert.save()
        self._hold()
        investigation = self._row("slot:now", status=InvestigationStatus.RUNNING)

        release = self._finish(investigation, verdict)
        repeated = self._finish(investigation, verdict)

        expected = (self.request,) if action == HoldRelease.SEND else ()
        assert release.deliveries == repeated.deliveries == expected
        hold = platform_testing.hold_release(self.address)
        assert (hold.release_action, hold.released_by) == (action, HoldReleasedBy.VERDICT)
        investigation.refresh_from_db()
        assert (investigation.status, investigation.verdict) == (InvestigationStatus.DONE, verdict)

    @parameterized.expand(
        [
            ("an ungated firing that already went out", None, "false_positive", True),
            ("a firing the safety net already sent", HoldRelease.SEND, "false_positive", True),
            ("an unchanged verdict", None, "true_positive", False),
            ("a firing that was suppressed", HoldRelease.SUPPRESS, "false_positive", False),
        ]
    )
    def test_a_changed_verdict_is_announced_only_on_a_firing_that_went_out(
        self, _name: str, released: HoldRelease | None, verdict: str, announced: bool
    ) -> None:
        if released is not None:
            self._hold(released=released)
        self._row("slot:earlier", status=InvestigationStatus.DONE, verdict="true_positive")
        investigation = self._row("slot:now", status=InvestigationStatus.RUNNING)

        with patch("products.alerts.backend.investigation_release.platform.record_verdict_changed") as announce:
            release = self._finish(investigation, verdict)

        assert release.previous_verdict == "true_positive"
        assert announce.called is announced
