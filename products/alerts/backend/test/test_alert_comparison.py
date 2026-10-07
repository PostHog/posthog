from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest import TestCase

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
from products.alerts_platform.backend.facade.contracts import PlatformCheck, SourceCoverage, SourceVerdict
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
                alert_configuration=self.alert, state=state.value, triggered_metadata=metadata
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

        check = self._check(evaluation_key=evaluation_key_for_slot(slot_of(slot, slot)))

        assert self._verdict(check).coverage is coverage

    def test_a_snoozed_check_is_suppressed_on_both_stacks(self) -> None:
        verdict = self._verdict(self._check(state="snoozed"))

        assert (verdict.coverage, verdict.state) == (SourceCoverage.SUPPRESSED, "snoozed")

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
