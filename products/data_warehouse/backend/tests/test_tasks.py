from datetime import date, datetime

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.response import Response

from posthog.ducklake import cp_teams
from posthog.models import Organization, Team

from products.data_warehouse.backend.tasks.tasks import sync_team_earliest_event_date


@pytest.fixture(autouse=True)
def _reset_cp_cache():
    cp_teams.clear_cache()
    yield
    cp_teams.clear_cache()


def _team() -> tuple[Organization, Team]:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    return org, team


def _cp_rows(org: Organization, team: Team, earliest: date | None = None) -> list[dict]:
    return [
        {
            "org_id": str(org.id),
            "team_id": team.id,
            "schema_name": "env",
            "enabled": True,
            "backfill_enabled": True,
            "earliest_event_date": earliest.isoformat() if earliest else None,
        }
    ]


def _patch_org_rows(rows):
    return patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=rows)


@parameterized.expand(
    [
        ("pre_2015_clamped", datetime(2010, 3, 1), date(2015, 1, 1)),
        ("post_2015_kept", datetime(2020, 6, 15), date(2020, 6, 15)),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_resolves_and_pushes_to_control_plane(
    _name: str,
    earliest_dt: datetime | None,
    expected: date,
    mock_get_earliest: MagicMock,
    mock_update: MagicMock,
) -> None:
    # The provisioning-time task must apply the same clamp the backfill sensor uses and
    # persist the result on the team's duckgres control-plane row (the sensor's read source).
    org, team = _team()
    mock_get_earliest.return_value = earliest_dt
    mock_update.return_value = Response({}, status=200)

    with _patch_org_rows(_cp_rows(org, team)):
        sync_team_earliest_event_date(team.id)

    mock_update.assert_called_once_with(
        str(org.id), team.id, require_enabled=False, earliest_event_date=expected.isoformat()
    )


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_leaves_empty_team_unresolved(mock_get_earliest: MagicMock, mock_update: MagicMock) -> None:
    # A just-provisioned project plausibly has no events YET. A cached date is final, so
    # storing the no-history sentinel here would permanently exclude the team from
    # historical backfill; the task must store nothing and leave the sensor to resolve
    # it later.
    org, team = _team()
    mock_get_earliest.return_value = None

    with _patch_org_rows(_cp_rows(org, team)):
        sync_team_earliest_event_date(team.id)

    mock_update.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_skips_clickhouse_when_date_already_cached(
    mock_get_earliest: MagicMock, mock_update: MagicMock
) -> None:
    # Idempotent re-runs (dispatch retries, re-onboards) must not re-query ClickHouse or
    # re-push a date the control plane already holds.
    org, team = _team()

    with _patch_org_rows(_cp_rows(org, team, earliest=date(2019, 5, 1))):
        sync_team_earliest_event_date(team.id)

    mock_get_earliest.assert_not_called()
    mock_update.assert_not_called()


@parameterized.expand(
    [
        # A dispatch can race a deleted membership row — skip quietly for a de-onboarded team.
        ("no_cp_row", []),
        # An unreachable control plane must not raise or query ClickHouse: the sensor
        # resolves the date lazily once the CP is back.
        ("cp_unreachable", None),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_is_a_noop_without_a_readable_row(
    _name: str, rows, mock_get_earliest: MagicMock, mock_update: MagicMock
) -> None:
    org, team = _team()

    with _patch_org_rows(rows):
        sync_team_earliest_event_date(team.id)

    mock_get_earliest.assert_not_called()
    mock_update.assert_not_called()
