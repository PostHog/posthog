from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ChartDisplayType, EventsNode, IntervalType, TrendsFilter, TrendsQuery

from posthog.schema_enums import (
    AlertCalculationInterval,
    AlertState as InsightAlertState,
)

from products.alerts.backend.alert_comparison import INSIGHT_INTENTIONAL_DIVERGENCES, InsightCorrespondence
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, Threshold
from products.alerts.backend.platform_source_cycle import CAPACITY_REJECTED, evaluation_key_for_slot
from products.alerts_platform.backend.facade.api import slot_of
from products.alerts_platform.backend.facade.contracts import (
    PlatformCheck,
    SourceCoverage,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts_platform.backend.facade.testing import undeclared_policy_divergences
from products.product_analytics.backend.facade.models import Insight

SLOT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
KEY = evaluation_key_for_slot(slot_of(SLOT, SLOT))
CHECKED_AT = SLOT + timedelta(minutes=1)


def _platform_check(*, legacy_configuration_id: UUID | None, team_id: int, **overrides: Any) -> PlatformCheck:
    fields: dict[str, Any] = {
        "team_id": team_id,
        "configuration_id": uuid4(),
        "legacy_configuration_id": legacy_configuration_id,
        "alert_id": uuid4(),
        "grouping_key": "",
        "evaluation_key": KEY,
        "kind": "check",
        "previous_state": "not_firing",
        "state": "firing",
        "muted_notification": "none",
        "error_message": "",
        "occurred_at": CHECKED_AT,
    }
    fields.update(overrides)
    return PlatformCheck(**fields)


class TestInsightDivergenceDeclarations(TestCase):
    def test_every_policy_divergence_is_declared(self) -> None:
        assert undeclared_policy_divergences(InsightCorrespondence()) == frozenset()


@time_machine.travel(SLOT + timedelta(days=1), tick=False)
class TestInsightCorrespondence(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        insight = Insight.objects.create(
            team=self.team,
            name="insight",
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                interval=IntervalType.DAY,
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            ).model_dump(),
        )
        threshold = Threshold.objects.create(
            team=self.team, insight=insight, configuration={"type": "absolute", "bounds": {"upper": 100.0}}
        )
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            name="alert",
            calculation_interval=AlertCalculationInterval.HOURLY.value,
            config={"type": "TrendsAlertConfig", "series_index": 0},
            condition={"type": "absolute_value"},
            threshold=threshold,
        )

    def _production(self, *checks: tuple[InsightAlertState, timedelta], skipped: bool = False) -> list[AlertCheck]:
        rows = []
        for state, offset in checks:
            metadata = {"skipped_reason": "no data"} if skipped else None
            row = AlertCheck.objects.create(
                alert_configuration=self.alert,
                state=state.value,
                triggered_metadata=metadata,
                calculated_value=None if skipped else 42.0,
            )
            AlertCheck.objects.filter(id=row.id).update(created_at=SLOT + offset)
            rows.append(row)
        return rows

    def _check(self, **overrides: Any) -> PlatformCheck:
        return _platform_check(**{"legacy_configuration_id": self.alert.id, "team_id": self.team.id, **overrides})

    def _verdict(self, check: PlatformCheck) -> SourceVerdict:
        return InsightCorrespondence().verdicts_for([check])[check.ref]

    def test_a_check_pairs_with_productions_first_check_of_the_same_period(self) -> None:
        _, same_period = self._production(
            (InsightAlertState.NOT_FIRING, -timedelta(minutes=23)),
            (InsightAlertState.FIRING, timedelta(minutes=37)),
        )

        verdict = self._verdict(self._check())

        assert (verdict.coverage, verdict.state, verdict.evidence_id) == (
            SourceCoverage.EVALUATED,
            "firing",
            str(same_period.id),
        )

    def test_production_leaving_and_catching_up_are_dated_separately(self) -> None:
        self._production(
            (InsightAlertState.NOT_FIRING, timedelta(minutes=37)),
            (InsightAlertState.ERRORED, timedelta(minutes=97)),
            (InsightAlertState.FIRING, timedelta(minutes=157)),
        )

        verdict = self._verdict(self._check())

        assert (verdict.state, verdict.observed_at, verdict.caught_up_at) == (
            "not_firing",
            SLOT + timedelta(minutes=97),
            SLOT + timedelta(minutes=157),
        )

    @parameterized.expand(
        [
            ("no_check_since_the_slot", -timedelta(minutes=23), {}, SLOT, SourceCoverage.BEHIND),
            ("its_next_check_is_a_later_period", timedelta(minutes=97), {}, SLOT, SourceCoverage.BEHIND),
            (
                "an_alert_production_disabled",
                -timedelta(minutes=23),
                {"enabled": False},
                SLOT,
                SourceCoverage.SUPPRESSED,
            ),
            (
                "a_weekend_production_skips",
                -timedelta(minutes=23),
                {"skip_weekend": True},
                datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
                SourceCoverage.UNKNOWN,
            ),
        ]
    )
    def test_a_period_production_made_no_check_of(
        self, _name: str, offset: timedelta, alert_fields: dict[str, Any], slot: datetime, coverage: SourceCoverage
    ) -> None:
        self._production((InsightAlertState.NOT_FIRING, offset))
        AlertConfiguration.objects.filter(id=self.alert.id).update(**alert_fields)

        check = self._check(evaluation_key=evaluation_key_for_slot(slot_of(slot, slot)), occurred_at=slot)

        assert self._verdict(check).coverage is coverage

    @parameterized.expand(
        [
            # Production checks the same local day earlier than the platform's slot.
            (
                "an_earlier_check_of_the_same_day",
                AlertCalculationInterval.DAILY,
                "America/Los_Angeles",
                datetime(2026, 3, 4, 9, 52, tzinfo=UTC),
                datetime(2026, 3, 4, 9, 37, tzinfo=UTC),
                SourceCoverage.EVALUATED,
            ),
            # A fixed 31 days from February 1 would reach into March.
            (
                "february",
                AlertCalculationInterval.MONTHLY,
                "UTC",
                datetime(2026, 2, 1, 4, 30, tzinfo=UTC),
                datetime(2026, 3, 1, 4, 20, tzinfo=UTC),
                SourceCoverage.BEHIND,
            ),
            # Spring forward makes March 8 a 23-hour day, so a fixed 24 hours would reach into March 9.
            (
                "a_daylight_saving_day",
                AlertCalculationInterval.DAILY,
                "America/Los_Angeles",
                datetime(2026, 3, 8, 9, 0, tzinfo=UTC),
                datetime(2026, 3, 9, 7, 30, tzinfo=UTC),
                SourceCoverage.BEHIND,
            ),
            (
                "a_daylight_saving_week",
                AlertCalculationInterval.WEEKLY,
                "America/Los_Angeles",
                datetime(2026, 3, 2, 11, 0, tzinfo=UTC),
                datetime(2026, 3, 9, 7, 30, tzinfo=UTC),
                SourceCoverage.BEHIND,
            ),
            # Lord Howe springs forward 30 minutes, so its local 02:00 hour lasts from 02:30 to 03:00.
            (
                "a_half_hour_daylight_saving_hour",
                AlertCalculationInterval.HOURLY,
                "Australia/Lord_Howe",
                datetime(2026, 10, 3, 15, 40, tzinfo=UTC),
                datetime(2026, 10, 3, 16, 5, tzinfo=UTC),
                SourceCoverage.BEHIND,
            ),
        ]
    )
    def test_a_check_pairs_within_the_local_calendar_period_of_its_slot(
        self,
        _name: str,
        interval: AlertCalculationInterval,
        timezone: str,
        slot: datetime,
        production_check: datetime,
        coverage: SourceCoverage,
    ) -> None:
        self.team.timezone = timezone
        self.team.save()
        AlertConfiguration.objects.filter(id=self.alert.id).update(calculation_interval=interval.value)
        row = AlertCheck.objects.create(
            alert_configuration=self.alert, state=InsightAlertState.FIRING.value, calculated_value=42.0
        )
        AlertCheck.objects.filter(id=row.id).update(created_at=production_check)
        check = self._check(evaluation_key=evaluation_key_for_slot(slot_of(slot, slot)), occurred_at=slot)

        # Inside production's check retention, so the period decides rather than the retention cut.
        with time_machine.travel(slot + timedelta(days=1), tick=False):
            verdict = self._verdict(check)

        assert verdict.coverage is coverage

    def test_a_check_the_schedule_blocked_when_the_platform_decided_is_not_compared(self) -> None:
        self._production((InsightAlertState.FIRING, timedelta(minutes=5)))
        AlertConfiguration.objects.filter(id=self.alert.id).update(
            schedule_restriction={"blocked_windows": [{"start": "12:30", "end": "13:30"}]}
        )
        slot = SLOT + timedelta(minutes=25)
        check = self._check(
            evaluation_key=evaluation_key_for_slot(slot_of(slot, slot)), occurred_at=SLOT + timedelta(minutes=35)
        )

        assert self._verdict(check).coverage is SourceCoverage.UNKNOWN

    def _row(self, state: InsightAlertState, offset: timedelta, alert: AlertConfiguration | None = None) -> None:
        """A production row with no value and no error, the shape of both a snooze row and a healthy
        breakdown evaluation."""
        row = AlertCheck.objects.create(alert_configuration=alert or self.alert, state=state.value)
        AlertCheck.objects.filter(id=row.id).update(created_at=SLOT + offset)

    def test_a_snooze_row_is_not_paired_as_an_evaluation(self) -> None:
        self._row(InsightAlertState.SNOOZED, timedelta(minutes=5))
        self._production((InsightAlertState.FIRING, timedelta(minutes=37)))

        verdict = self._verdict(self._check())

        assert (verdict.coverage, verdict.state) == (SourceCoverage.EVALUATED, "firing")

    def test_a_healthy_breakdown_evaluation_without_a_value_is_paired(self) -> None:
        self._row(InsightAlertState.NOT_FIRING, timedelta(minutes=37))

        verdict = self._verdict(self._check(state="not_firing"))

        assert (verdict.coverage, verdict.state) == (SourceCoverage.EVALUATED, "not_firing")

    def test_alerts_read_across_several_history_queries_are_all_paired(self) -> None:
        other = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.alert.insight,
            name="other",
            calculation_interval=self.alert.calculation_interval,
        )
        self._row(InsightAlertState.FIRING, timedelta(minutes=37))
        self._row(InsightAlertState.FIRING, timedelta(minutes=37), alert=other)
        checks = [self._check(), self._check(legacy_configuration_id=other.id)]

        with patch(f"{InsightCorrespondence.__module__}.ALERTS_PER_QUERY", 1):
            verdicts = InsightCorrespondence().verdicts_for(checks)

        assert [verdicts[check.ref].coverage for check in checks] == [SourceCoverage.EVALUATED] * 2

    def test_a_skipped_production_check_is_not_catching_up(self) -> None:
        self._production((InsightAlertState.FIRING, timedelta(minutes=37)))
        self._production((InsightAlertState.NOT_FIRING, timedelta(minutes=97)), skipped=True)

        verdict = self._verdict(self._check(state="not_firing"))

        assert (verdict.state, verdict.caught_up_at) == ("firing", None)

    def test_production_checks_past_the_catch_up_horizon_are_not_read(self) -> None:
        self._production(
            (InsightAlertState.FIRING, timedelta(minutes=37)),
            *[(InsightAlertState.FIRING, timedelta(days=3, minutes=n)) for n in range(5)],
        )

        with patch(f"{InsightCorrespondence.__module__}.MAX_CHECKS_PER_BATCH", 3):
            verdict = self._verdict(self._check())

        assert verdict.coverage is SourceCoverage.EVALUATED

    @parameterized.expand(
        [
            ("production_still_snoozes_it", True, "snoozed", SuppressionReason.MUTED),
            ("production_has_switched_it_off", False, None, SuppressionReason.DISABLED),
        ]
    )
    def test_a_snoozed_check_is_suppressed_on_both_stacks(
        self, _name: str, enabled: bool, state: str | None, reason: SuppressionReason
    ) -> None:
        AlertConfiguration.objects.filter(id=self.alert.id).update(enabled=enabled)

        verdict = self._verdict(self._check(state="snoozed"))

        assert (verdict.coverage, verdict.state, verdict.suppressed_by) == (SourceCoverage.SUPPRESSED, state, reason)

    @parameterized.expand(
        [
            ("an_unslotted_key", {"evaluation_key": "window:2026-10-07T12:00:00+00:00"}),
            ("no_insight_alert", {"legacy_configuration_id": None}),
            ("another_projects_alert", {"team_id": -1}),
            (
                "a_slot_past_retention",
                {"evaluation_key": evaluation_key_for_slot(slot_of(SLOT - timedelta(days=14), SLOT))},
            ),
        ]
    )
    def test_a_check_that_names_no_production_check_cannot_be_answered(
        self, _name: str, overrides: dict[str, Any]
    ) -> None:
        self._production((InsightAlertState.FIRING, timedelta(minutes=37)))
        check = self._check(**overrides)
        # A batch spans teams, so the alert's own team reads it in the same call.
        owner = self._check()

        verdicts = InsightCorrespondence().verdicts_for([check, owner])

        assert verdicts[check.ref].coverage is SourceCoverage.UNKNOWN
        assert verdicts[owner.ref].coverage is SourceCoverage.EVALUATED

    def test_a_check_production_skipped_cannot_be_answered(self) -> None:
        self._production((InsightAlertState.FIRING, timedelta(minutes=37)), skipped=True)

        assert self._verdict(self._check()).coverage is SourceCoverage.UNKNOWN

    def test_only_a_capacity_refusal_is_declared(self) -> None:
        self._production((InsightAlertState.FIRING, timedelta(minutes=37)))
        refused = self._check(
            state="not_firing",
            error_message=CAPACITY_REJECTED,
        )
        failed = self._check(
            state="not_firing",
            error_message="query timed out",
        )

        verdicts = InsightCorrespondence().verdicts_for([refused, failed])
        (declared,) = INSIGHT_INTENTIONAL_DIVERGENCES

        assert declared.recognizes(refused, verdicts[refused.ref])
        assert not declared.recognizes(failed, verdicts[failed.ref])
