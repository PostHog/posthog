from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.api import record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    CheckFailure,
    GroupOutcome,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout
from products.alerts_platform.backend.facade.testing import (
    configuration,
    count_still_due,
    create_configuration,
    set_due_at,
)
from products.billing_alerts.backend.platform_source_cycle import evaluate_billing_batch
from products.billing_alerts.backend.temporal.platform_evaluate import EVALUATION_BUDGET

_MODULE = "products.billing_alerts.backend.platform_source_cycle"
CUTOFF = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
DUE_AT = CUTOFF - timedelta(minutes=1)


def _billing_response(current: int | None, projected: int | None = None) -> dict[str, Any]:
    customer: dict[str, Any] = {}
    if current is not None:
        customer["current_total_amount_usd_after_discount"] = str(current)
    if projected is not None:
        customer["projected_total_amount_usd_with_limit_after_discount"] = str(projected)
    return {"customer": customer}


def _decided(outcome: PlatformAlertOutcome) -> GroupOutcome | CheckFailure:
    """The one verdict an ungrouped billing check reports, or its failure."""
    return outcome.failure or outcome.groups[0]


@time_machine.travel(CUTOFF, tick=False)
class TestPlatformBillingEvaluation(BaseTest):
    def _alert(
        self, *, source_config: dict[str, Any] | None = None, name: str = "Period spend cap", **fields: Any
    ) -> UUID:
        with team_scope(self.team.id):
            return create_configuration(
                team=self.team,
                name=name,
                source_kind=SourceKind.BILLING.value,
                source_config={"metric": "spend", "condition": {"threshold_value": "100"}}
                if source_config is None
                else source_config,
                check_interval_minutes=60,
                cooldown_minutes=0,
                next_check_at=DUE_AT,
                **fields,
            ).id

    def _evaluate(self, *responses: dict[str, Any] | Exception) -> tuple[SourceBatchEvaluation, Any]:
        side_effect = [r if isinstance(r, Exception) else (r, 12) for r in responses]
        with patch(f"{_MODULE}.fetch_billing_status", side_effect=side_effect) as fetch:
            evaluation = evaluate_billing_batch(self.team.id, slot_of(DUE_AT, CUTOFF), CUTOFF)
        return evaluation, fetch

    @parameterized.expand(
        [
            ("spend_over", "spend", _billing_response(150, projected=50), AlertEventKind.FIRING, 150.0),
            ("spend_under", "spend", _billing_response(50, projected=150), AlertEventKind.CHECK, 50.0),
            ("projected_over", "projected_spend", _billing_response(50, projected=150), AlertEventKind.FIRING, 150.0),
        ]
    )
    def test_a_platform_row_is_checked_against_its_own_metric_and_threshold(
        self, _name: str, metric: str, response: dict[str, Any], kind: AlertEventKind, value: float
    ) -> None:
        self._alert(source_config={"metric": metric, "condition": {"threshold_value": "100.50"}})

        evaluation, fetch = self._evaluate(response)

        (outcome,) = evaluation.outcomes
        (group,) = outcome.groups
        assert (group.kind, group.value, outcome.disable, outcome.evaluation_key) == (
            kind,
            value,
            False,
            f"slot:{slot_of(DUE_AT, CUTOFF)}",
        )
        assert fetch.call_args.args == (self.organization,)
        assert evaluation.deliveries == ()

    @parameterized.expand(
        [
            ("no_total_yet", _billing_response(None)),
            ("billing_service_down", ConnectionError("billing service timed out")),
            ("billing_returns_no_customer", {}),
            ("billing_returns_an_unreadable_amount", {"customer": {"current_total_amount_usd_after_discount": "n/a"}}),
        ]
    )
    def test_a_check_that_reads_no_total_leaves_a_firing_alert_firing_quietly(
        self, _name: str, response: dict[str, Any] | Exception
    ) -> None:
        configuration_id = self._alert()
        fired, _ = self._evaluate(_billing_response(150))
        with team_scope(self.team.id):
            record_outcomes(self.team.id, fired.outcomes, CUTOFF)
            set_due_at(configuration_id, DUE_AT)

        evaluation, _ = self._evaluate(response)

        (outcome,) = evaluation.outcomes
        decided = _decided(outcome)
        assert (decided.kind, decided.new_state, outcome.consecutive_failures, outcome.disable) == (
            AlertEventKind.CHECK,
            "firing",
            0,
            False,
        )

    @parameterized.expand(
        [
            ("no_metric", {"condition": {"threshold_value": "100"}}),
            ("unknown_metric", {"metric": "usage", "condition": {"threshold_value": "100"}}),
            ("no_threshold", {"metric": "spend", "condition": {}}),
            ("unreadable_threshold", {"metric": "spend", "condition": {"threshold_value": "lots"}}),
        ]
    )
    def test_a_row_billing_cannot_read_fails_toward_breaking(self, _name: str, source_config: dict[str, Any]) -> None:
        self._alert(source_config=source_config)

        evaluation, _ = self._evaluate(_billing_response(150))

        (outcome,) = evaluation.outcomes
        assert outcome.failure is not None
        assert (outcome.consecutive_failures, outcome.disable) == (1, False)

    def test_a_mute_on_the_platform_row_holds_the_fire(self) -> None:
        self._alert(snooze_until=CUTOFF + timedelta(hours=2))

        evaluation, _ = self._evaluate(_billing_response(150))

        (outcome,) = evaluation.outcomes
        (group,) = outcome.groups
        assert (group.kind, group.muted_notification) == (AlertEventKind.CHECK, "fire")

    def test_one_billing_call_serves_every_alert_of_an_organization_in_a_batch(self) -> None:
        configuration_ids = [self._alert(name="First"), self._alert(name="Second")]

        evaluation, fetch = self._evaluate(_billing_response(150))
        with team_scope(self.team.id):
            record_outcomes(self.team.id, evaluation.outcomes, CUTOFF)
            next_checks = {configuration(c).next_check_at for c in configuration_ids}

        assert fetch.call_count == 1
        assert [o.groups[0].kind for o in evaluation.outcomes] == [AlertEventKind.FIRING, AlertEventKind.FIRING]
        assert len(next_checks) == 1

    def test_checks_past_the_payload_bound_are_left_due(self) -> None:
        configuration_ids = [self._alert(name=f"Bound {n}") for n in range(3)]

        # The first outcome alone overruns a 25-byte budget; the two after it fit.
        with (
            patch(f"{_MODULE}.payload_bytes", side_effect=[30, 10, 10]),
            patch(f"{_MODULE}.MAX_BATCH_PAYLOAD_BYTES", 25),
        ):
            evaluation, _ = self._evaluate(_billing_response(150))
        with team_scope(self.team.id):
            record_outcomes(self.team.id, evaluation.outcomes, CUTOFF)
            still_due = count_still_due(configuration_ids, at=CUTOFF)

        assert (len(evaluation.outcomes), evaluation.omitted, still_due) == (2, 1, 1)


def test_the_binding_holds_the_whole_batch() -> None:
    assert source_evaluation_timeout(SourceKind.BILLING) > EVALUATION_BUDGET
