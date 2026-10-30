from datetime import date
from uuid import UUID

import time_machine

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.events_plan_deletion import (
    PlanDeletionState,
    admitted,
    after_pass,
    deletion_months,
    is_shorter_window,
    next_cleanup_on,
    retention_window,
    with_window,
)
from posthog.models.events_retention_config import TeamEventsRetention

TODAY = date(2026, 11, 3)


class TestPlanDeletionRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("on_a_cleanup_day", date(2026, 11, 3), date(2027, 2, 3)),
            ("between_cleanup_days", date(2026, 11, 15), date(2027, 3, 3)),
        ]
    )
    def test_admitted_lands_on_a_cleanup_day(self, _name: str, today: date, next_deletion_on: date) -> None:
        assert admitted(12, today) == PlanDeletionState(months=12, next_deletion_on=next_deletion_on)

    @parameterized.expand(
        [
            ("shorter_window_pushes_a_near_pass", 24, date(2026, 12, 3), 12, date(2027, 2, 3), True),
            ("shorter_window_keeps_a_later_pass", 24, date(2027, 4, 3), 12, date(2027, 4, 3), True),
            ("longer_window_keeps_the_pass", 12, date(2026, 12, 3), 24, date(2026, 12, 3), False),
            ("same_window_keeps_the_pass", 12, date(2026, 12, 3), 12, date(2026, 12, 3), False),
        ]
    )
    def test_with_window(
        self, _name: str, months: int, next_on: date, window: int, expected_next_on: date, shorter: bool
    ) -> None:
        state = PlanDeletionState(months=months, next_deletion_on=next_on)

        assert is_shorter_window(state, window) is shorter
        assert with_window(state, window, TODAY) == PlanDeletionState(months=window, next_deletion_on=expected_next_on)

    def test_after_pass(self) -> None:
        state = PlanDeletionState(months=12, next_deletion_on=TODAY)

        assert after_pass(state, TODAY) == PlanDeletionState(months=12, next_deletion_on=date(2027, 2, 3))

    @parameterized.expand(
        [
            ("default_on_the_longest_plan", 84, None, 24),
            ("plan_shorter_than_the_default", 12, None, 12),
            ("set_window_longer_than_the_default", 84, 36, 36),
            ("set_window_longer_than_the_plan", 24, 36, 24),
        ]
    )
    def test_retention_window(self, _name: str, plan: int, setting: int | None, expected: int) -> None:
        assert retention_window(plan, setting) == expected

    @parameterized.expand(
        [
            ("monthly_setting", 6, True, None, 6),
            ("setting_waits_for_a_pass", 6, False, None, None),
            ("pass_window", 6, False, 6, 6),
            ("monthly_setting_shorter_than_the_pass", 6, True, 12, 6),
            ("pass_shorter_than_a_monthly_setting", 24, True, 12, 12),
            ("nothing_set", None, False, None, None),
        ]
    )
    def test_deletion_months(
        self, _name: str, setting: int | None, monthly: bool, pass_months: int | None, expected: int | None
    ) -> None:
        retention = (
            TeamEventsRetention(organization_id=UUID(int=0), team_id=1, months=setting, delete_monthly=monthly)
            if setting is not None
            else None
        )

        assert deletion_months(retention, pass_months) == expected

    @parameterized.expand(
        [
            ("before_the_run", "2026-11-04T04:59:00Z", date(2026, 11, 3)),
            ("after_the_run", "2026-11-04T05:00:00Z", date(2026, 12, 3)),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_next_cleanup_on(self, _name: str, now: str, expected: date) -> None:
        with time_machine.travel(now, tick=False):
            assert next_cleanup_on() == expected
