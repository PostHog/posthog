from datetime import date

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.events_plan_deletion import (
    PlanDeletionState,
    admitted,
    after_pass,
    deletion_months,
    is_downgrade,
    with_plan,
)

TODAY = date(2026, 11, 3)


class TestPlanDeletionRules(SimpleTestCase):
    def test_admitted(self) -> None:
        assert admitted(12, TODAY) == PlanDeletionState(months=12, next_deletion_on=date(2027, 2, 3))

    @parameterized.expand(
        [
            ("downgrade_pushes_a_near_pass", 24, date(2026, 12, 3), 12, date(2027, 2, 3), True),
            ("downgrade_keeps_a_later_pass", 24, date(2027, 4, 3), 12, date(2027, 4, 3), True),
            ("upgrade_keeps_the_pass", 12, date(2026, 12, 3), 24, date(2026, 12, 3), False),
            ("same_plan_keeps_the_pass", 12, date(2026, 12, 3), 12, date(2026, 12, 3), False),
        ]
    )
    def test_with_plan(
        self, _name: str, months: int, next_on: date, plan: int, expected_next_on: date, downgrade: bool
    ) -> None:
        state = PlanDeletionState(months=months, next_deletion_on=next_on)

        assert is_downgrade(state, plan) is downgrade
        assert with_plan(state, plan, TODAY) == PlanDeletionState(months=plan, next_deletion_on=expected_next_on)

    def test_after_pass(self) -> None:
        state = PlanDeletionState(months=12, next_deletion_on=TODAY)

        assert after_pass(state, TODAY) == PlanDeletionState(months=12, next_deletion_on=date(2027, 2, 3))

    @parameterized.expand(
        [
            ("setting_shorter_than_plan_on_a_pass", 6, 12, True, 6),
            ("setting_applies_without_a_pass", 6, 12, False, 6),
            ("plan_applies_on_a_pass", None, 12, True, 12),
            ("plan_waits_for_a_pass", None, 12, False, None),
            ("plan_shorter_than_setting_on_a_pass", 24, 12, True, 12),
            ("longest_plan_deletes_nothing", None, 84, True, None),
            ("nothing_set", None, None, False, None),
        ]
    )
    def test_deletion_months(
        self, _name: str, setting: int | None, plan: int | None, pass_due: bool, expected: int | None
    ) -> None:
        assert deletion_months(setting, plan, pass_due) == expected
