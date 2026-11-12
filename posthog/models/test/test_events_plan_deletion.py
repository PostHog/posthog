from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.db import transaction
from django.test import SimpleTestCase, override_settings

from celery.exceptions import Retry
from parameterized import parameterized

from posthog.models.events_plan_deletion import (
    PlanDeletionState,
    TeamEventsPlanDeletion,
    admitted,
    after_pass,
    apply_events_retention_change,
    cleanup_date,
    deleting_plans,
    deletion_months,
    is_shorter_period,
    next_cleanup_on,
    report_upcoming_deletions,
    reschedule_plan_deletions,
    with_period,
)
from posthog.models.events_retention_config import TeamEventsRetention, TeamEventsRetentionConfig
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.tasks.tasks import report_events_retention_shortened, report_upcoming_events_deletions

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


_TWO_YEAR_PLAN = [{"key": "product_analytics_data_retention", "limit": 2, "unit": "years"}]


def _organization_with_admin(name: str) -> Organization:
    organization = Organization.objects.create(name=name)
    admin_email = f"admin@{name.lower()}.example.com"
    User.objects.create_and_join(organization, admin_email, None, level=OrganizationMembership.Level.ADMIN)
    User.objects.create_and_join(organization, f"member@{name.lower()}.example.com", None)
    return organization


def _team_with_pass(pass_months: int = 24) -> Team:
    organization = _organization_with_admin("Scheduled")
    Organization.objects.filter(id=organization.id).update(available_product_features=_TWO_YEAR_PLAN)
    team = Team.objects.create(organization=organization, name="Scheduled", event_retention_months=24)
    TeamEventsPlanDeletion.objects.create(team=team, months=pass_months, next_deletion_on=date(2027, 2, 3))
    return team


def _captured(scoped_capture: MagicMock) -> list[dict]:
    return [call.kwargs for call in scoped_capture.return_value.__enter__.return_value.call_args_list]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "deleting,pass_months,setting_months,notified",
    [
        pytest.param(True, 24, None, True, id="pass_at_the_next_cleanup"),
        pytest.param(False, 24, None, False, id="deletion_turned_off"),
        pytest.param(True, 36, None, False, id="period_shortened_after_pass"),
        pytest.param(True, 12, 12, False, id="setting_already_deletes_monthly"),
        pytest.param(True, 24, 36, True, id="setting_past_the_plan"),
    ],
)
@override_settings(CLOUD_DEPLOYMENT="US")
def test_report_upcoming_events_deletions_tells_admins_once_two_weeks_before_the_pass(
    deleting: bool, pass_months: int, setting_months: int | None, notified: bool
):
    team = _team_with_pass(pass_months)
    if setting_months is not None:
        TeamEventsRetentionConfig.objects.create(team=team, events_retention_months=setting_months)

    with (
        override_settings(EVENTS_DATA_RETENTION_ENFORCED=deleting),
        patch("posthog.models.events_plan_deletion.is_cloud", return_value=True),
        patch("posthog.models.events_plan_deletion.ph_scoped_capture") as scoped_capture,
    ):
        for days in range(22):
            with time_machine.travel(datetime(2027, 1, 13, 18, tzinfo=UTC) + timedelta(days=days), tick=False):
                report_upcoming_deletions()

    assert _captured(scoped_capture) == (
        [
            {
                "distinct_id": User.objects.get(email="admin@scheduled.example.com").distinct_id,
                "event": "events retention deletion upcoming",
                "properties": {
                    "organization_name": "Scheduled",
                    "retention_months": 24,
                    "deletion_scheduled_on": "2027-02-03",
                    "$update_person_last_seen_at": False,
                },
                "groups": {"organization": str(team.organization_id)},
            }
        ]
        if notified
        else []
    )


def _failing_client(_region: str, on_error: Callable[[Exception, object], None]) -> MagicMock:
    return MagicMock(shutdown=MagicMock(side_effect=lambda: on_error(ConnectionError("ingestion is down"), None)))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "send",
    [
        pytest.param(
            lambda team: report_events_retention_shortened.delay(str(team.organization_id), {"retention_months": 24}),
            id="period_shortened",
        ),
        pytest.param(lambda _team: report_upcoming_events_deletions.delay(), id="deletion_upcoming"),
    ],
)
@override_settings(CLOUD_DEPLOYMENT="US", EVENTS_DATA_RETENTION_ENFORCED=True)
def test_a_failed_send_retries(send: Callable[[Team], object]):
    team = _team_with_pass()

    with (
        time_machine.travel("2027-01-20T18:00:00Z", tick=False),
        patch("posthog.models.events_plan_deletion.is_cloud", return_value=True),
        patch("posthog.ph_client.get_client", side_effect=_failing_client),
        pytest.raises(Retry),
    ):
        send(team)


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US", EVENTS_DATA_RETENTION_ENFORCED=True)
def test_a_downgrade_right_after_an_upgrade_pushes_the_pass():
    organization = Organization.objects.create(name="Cycled", available_product_features=_TWO_YEAR_PLAN)
    team = Team.objects.create(organization=organization, name="Cycled", event_retention_months=24)
    TeamEventsPlanDeletion.objects.create(team=team, months=24, next_deletion_on=date(2026, 12, 3))

    with time_machine.travel("2026-11-20T18:00:00Z", tick=False):
        for features, previous_months in (([], 24), (_TWO_YEAR_PLAN, 84)):
            Organization.objects.filter(id=organization.id).update(available_product_features=features)
            apply_events_retention_change(organization, previous_months, False)

    assert TeamEventsPlanDeletion.objects.get(team=team).state == PlanDeletionState(
        months=24, next_deletion_on=date(2027, 3, 3)
    )


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US")
def test_a_team_that_joins_deletion_after_a_downgrade_hears_before_its_first_pass():
    organization = _organization_with_admin("Late")
    team = Team.objects.create(organization=organization, name="Late", event_retention_months=84)

    with (
        patch("posthog.models.events_plan_deletion.is_cloud", return_value=True),
        patch("posthog.models.events_plan_deletion.ph_scoped_capture") as scoped_capture,
    ):
        with (
            override_settings(EVENTS_DATA_RETENTION_ENFORCED=False),
            time_machine.travel("2026-11-20T18:00:00Z", tick=False),
        ):
            Organization.objects.filter(id=organization.id).update(available_product_features=_TWO_YEAR_PLAN)
            apply_events_retention_change(organization, 84, False)
        with override_settings(EVENTS_DATA_RETENTION_ENFORCED=True):
            with time_machine.travel("2026-12-03T18:00:00Z", tick=False), transaction.atomic():
                reschedule_plan_deletions(deleting_plans(Team.objects.filter(id=team.id)), cleanup_date())
            with time_machine.travel("2027-02-17T18:00:00Z", tick=False):
                report_upcoming_deletions()

    assert [
        (capture["event"], capture["properties"]["deletion_scheduled_on"]) for capture in _captured(scoped_capture)
    ] == [
        ("events retention period shortened", None),
        ("events retention deletion upcoming", "2027-03-03"),
    ]
