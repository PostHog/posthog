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
    is_shorter_period,
    next_cleanup_on,
    with_period,
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
            ("shorter_period_pushes_a_near_pass", 24, date(2026, 12, 3), 12, date(2027, 2, 3), True),
            ("shorter_period_keeps_a_later_pass", 24, date(2027, 4, 3), 12, date(2027, 4, 3), True),
            ("longer_period_keeps_the_pass", 12, date(2026, 12, 3), 24, date(2026, 12, 3), False),
            ("same_period_keeps_the_pass", 12, date(2026, 12, 3), 12, date(2026, 12, 3), False),
        ]
    )
    def test_with_period(
        self, _name: str, months: int, next_on: date, period: int, expected_next_on: date, shorter: bool
    ) -> None:
        state = PlanDeletionState(months=months, next_deletion_on=next_on)

        assert is_shorter_period(state, period) is shorter
        assert with_period(state, period, TODAY) == PlanDeletionState(months=period, next_deletion_on=expected_next_on)

    @parameterized.expand(
        [
            ("due_pass", TODAY, date(2027, 2, 3)),
            ("pass_moved_later_during_the_run", date(2027, 3, 3), date(2027, 3, 3)),
        ]
    )
    def test_after_pass(self, _name: str, next_on: date, expected_next_on: date) -> None:
        state = PlanDeletionState(months=12, next_deletion_on=next_on)

        assert after_pass(state, TODAY) == PlanDeletionState(months=12, next_deletion_on=expected_next_on)

    @parameterized.expand(
        [
            ("setting", 6, None, 6),
            ("pass_period", None, 6, 6),
            ("setting_shorter_than_the_pass", 6, 12, 6),
            ("pass_shorter_than_the_setting", 24, 12, 12),
            ("nothing_set", None, None, None),
        ]
    )
    def test_deletion_months(
        self, _name: str, setting: int | None, pass_months: int | None, expected: int | None
    ) -> None:
        retention = (
            TeamEventsRetention(organization_id=UUID(int=0), team_id=1, months=setting) if setting is not None else None
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
