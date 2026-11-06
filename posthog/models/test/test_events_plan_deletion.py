from collections.abc import Callable
from datetime import date
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
    TeamEventsRetentionDowngrade,
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
from posthog.models.events_retention_config import TeamEventsRetention
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.tasks.tasks import report_events_retention_shortened

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
_THREE_YEAR_PLAN = [{"key": "product_analytics_data_retention", "limit": 3, "unit": "years"}]


def _organization_with_admin(name: str) -> Organization:
    organization = Organization.objects.create(name=name)
    admin_email = f"admin@{name.lower()}.example.com"
    User.objects.create_and_join(organization, admin_email, None, level=OrganizationMembership.Level.ADMIN)
    User.objects.create_and_join(organization, f"member@{name.lower()}.example.com", None)
    return organization


def _downgraded_team(features: list[dict], pass_months: int = 24, name: str = "Downgraded") -> Team:
    organization = _organization_with_admin(name)
    Organization.objects.filter(id=organization.id).update(available_product_features=features)
    team = Team.objects.create(organization=organization, name=name, event_retention_months=24)
    TeamEventsPlanDeletion.objects.create(team=team, months=pass_months, next_deletion_on=date(2027, 2, 3))
    TeamEventsRetentionDowngrade.objects.create(team=team, downgraded_from_months=84)
    return team


def _downgraded_from(team: Team) -> int | None:
    return (
        TeamEventsRetentionDowngrade.objects.filter(team=team).values_list("downgraded_from_months", flat=True).first()
    )


def _captured(scoped_capture: MagicMock) -> list[dict]:
    return [call.kwargs for call in scoped_capture.return_value.__enter__.return_value.call_args_list]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "now,features,deleting,pass_months,notified,marker_left",
    [
        pytest.param("2027-01-20T18:00:00Z", _TWO_YEAR_PLAN, True, 24, True, None, id="two_weeks_before_the_pass"),
        pytest.param("2027-01-13T18:00:00Z", _TWO_YEAR_PLAN, True, 24, False, 84, id="three_weeks_before_the_pass"),
        pytest.param("2027-01-20T18:00:00Z", [], True, 24, False, None, id="plan_raised_again"),
        pytest.param("2027-01-20T18:00:00Z", _TWO_YEAR_PLAN, False, 24, False, 84, id="deletion_turned_off"),
        pytest.param("2027-01-20T18:00:00Z", _TWO_YEAR_PLAN, True, 36, False, 84, id="period_shortened_after_pass"),
    ],
)
@override_settings(CLOUD_DEPLOYMENT="US")
def test_report_upcoming_events_deletions_tells_admins_once(
    now: str, features: list[dict], deleting: bool, pass_months: int, notified: bool, marker_left: int | None
):
    team = _downgraded_team(features, pass_months)

    with (
        override_settings(EVENTS_DATA_RETENTION_ENFORCED=deleting),
        time_machine.travel(now, tick=False),
        patch("posthog.models.events_plan_deletion.is_cloud", return_value=True),
        patch("posthog.models.events_plan_deletion.ph_scoped_capture") as scoped_capture,
    ):
        report_upcoming_deletions()
        report_upcoming_deletions()

    assert _captured(scoped_capture) == (
        [
            {
                "distinct_id": User.objects.get(email="admin@downgraded.example.com").distinct_id,
                "event": "events retention deletion upcoming",
                "properties": {
                    "organization_name": "Downgraded",
                    "previous_retention_months": 84,
                    "retention_months": 24,
                    "deletion_scheduled_on": "2027-02-03",
                },
                "groups": {"organization": str(team.organization_id)},
            }
        ]
        if notified
        else []
    )
    assert _downgraded_from(team) == marker_left


def _clients_failing_on(
    calls: set[int],
) -> tuple[list[MagicMock], Callable[[str, Callable[[Exception, object], None]], MagicMock]]:
    clients: list[MagicMock] = []

    def get_client(_region: str, on_error: Callable[[Exception, object], None]) -> MagicMock:
        failing = len(clients) in calls
        clients.append(
            MagicMock(
                shutdown=MagicMock(
                    side_effect=lambda: on_error(ConnectionError("ingestion is down"), None) if failing else None
                )
            )
        )
        return clients[-1]

    return clients, get_client


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US", EVENTS_DATA_RETENTION_ENFORCED=True)
def test_report_upcoming_events_deletions_keeps_only_undelivered_markers():
    teams = [_downgraded_team(_TWO_YEAR_PLAN, name=name) for name in ("First", "Second")]
    _clients, get_client = _clients_failing_on({1})

    with (
        time_machine.travel("2027-01-20T18:00:00Z", tick=False),
        patch("posthog.models.events_plan_deletion.is_cloud", return_value=True),
        patch("posthog.ph_client.get_client", side_effect=get_client),
        pytest.raises(ConnectionError),
    ):
        report_upcoming_deletions()

    assert sorted((_downgraded_from(team) for team in teams), key=str) == [84, None]


@pytest.mark.django_db
@override_settings(CLOUD_DEPLOYMENT="US")
def test_report_events_retention_shortened_retries_a_failed_send():
    team = _downgraded_team(_TWO_YEAR_PLAN)
    _clients, get_client = _clients_failing_on({0})

    with (
        patch("posthog.models.events_plan_deletion.is_cloud", return_value=True),
        patch("posthog.ph_client.get_client", side_effect=get_client),
        pytest.raises(Retry),
    ):
        report_events_retention_shortened.delay(str(team.organization_id), {"retention_months": 24})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "start_features,start_months,changes",
    [
        pytest.param(_TWO_YEAR_PLAN, 24, [([], 24), (_TWO_YEAR_PLAN, 84)], id="downgrade_right_after_an_upgrade"),
        pytest.param([], 84, [(_THREE_YEAR_PLAN, 84), (_TWO_YEAR_PLAN, 36)], id="second_downgrade_before_the_pass"),
    ],
)
@override_settings(CLOUD_DEPLOYMENT="US", EVENTS_DATA_RETENTION_ENFORCED=True)
def test_downgrades_push_the_pass_and_keep_the_longest_previous_plan(
    start_features: list[dict], start_months: int, changes: list[tuple[list[dict], int]]
):
    organization = Organization.objects.create(name="Cycled", available_product_features=start_features)
    team = Team.objects.create(organization=organization, name="Cycled", event_retention_months=start_months)
    TeamEventsPlanDeletion.objects.create(team=team, months=start_months, next_deletion_on=date(2026, 12, 3))

    with time_machine.travel("2026-11-20T18:00:00Z", tick=False):
        for features, previous_months in changes:
            Organization.objects.filter(id=organization.id).update(available_product_features=features)
            apply_events_retention_change(organization, previous_months, False)

    assert TeamEventsPlanDeletion.objects.get(team=team).state == PlanDeletionState(
        months=24, next_deletion_on=date(2027, 3, 3)
    )
    assert _downgraded_from(team) == 84


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
            with time_machine.travel("2027-02-20T18:00:00Z", tick=False):
                report_upcoming_deletions()

    assert [
        (capture["event"], capture["properties"]["deletion_scheduled_on"]) for capture in _captured(scoped_capture)
    ] == [
        ("events retention period shortened", None),
        ("events retention deletion upcoming", "2027-03-03"),
    ]
