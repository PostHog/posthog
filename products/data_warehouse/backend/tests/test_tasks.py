from datetime import date, datetime

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.response import Response

from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam
from posthog.models import Organization, Team

from products.data_warehouse.backend.tasks.tasks import sync_team_earliest_event_date


def _onboarded_team(earliest: date | None = None) -> tuple[Organization, Team]:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    server = DuckgresServer.objects.create(
        organization=org, host="h", port=5432, database="ducklake", username="root", password="x"
    )
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="env", earliest_event_date=earliest)
    return org, team


@parameterized.expand(
    [
        ("pre_2015_clamped", datetime(2010, 3, 1), date(2015, 1, 1)),
        ("post_2015_kept", datetime(2020, 6, 15), date(2020, 6, 15)),
    ]
)
@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_resolves_and_dual_writes(
    _name: str,
    earliest_dt: datetime | None,
    expected: date,
    mock_get_earliest: MagicMock,
    mock_update: MagicMock,
) -> None:
    # The provisioning-time task must apply the same clamp the backfill sensor uses, and
    # write the result to BOTH the Django row (the sensor's read source) and the duckgres
    # control-plane team row.
    org, team = _onboarded_team()
    mock_get_earliest.return_value = earliest_dt
    mock_update.return_value = Response({}, status=200)

    sync_team_earliest_event_date(team.id)

    assert DuckgresServerTeam.objects.get(team=team).earliest_event_date == expected
    mock_update.assert_called_once_with(
        org.id, team.id, require_enabled=False, earliest_event_date=expected.isoformat()
    )


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_leaves_empty_team_unresolved(mock_get_earliest: MagicMock, mock_update: MagicMock) -> None:
    # A just-provisioned project plausibly has no events YET. A cached date is final, so
    # storing the no-history sentinel here would permanently exclude the team from
    # historical backfill; the task must leave the row NULL for the sensor to resolve
    # later, and push nothing to the control plane.
    _, team = _onboarded_team()
    mock_get_earliest.return_value = None

    sync_team_earliest_event_date(team.id)

    assert DuckgresServerTeam.objects.get(team=team).earliest_event_date is None
    mock_update.assert_not_called()


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_skips_clickhouse_when_date_already_cached(
    mock_get_earliest: MagicMock, mock_update: MagicMock
) -> None:
    # Idempotent re-runs (dispatch retries, re-onboards) must not re-query ClickHouse,
    # but still converge the control-plane row from the cached value.
    org, team = _onboarded_team(earliest=date(2019, 5, 1))
    mock_update.return_value = Response({}, status=200)

    sync_team_earliest_event_date(team.id)

    mock_get_earliest.assert_not_called()
    mock_update.assert_called_once_with(org.id, team.id, require_enabled=False, earliest_event_date="2019-05-01")


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_control_plane_failure_keeps_django_write(
    mock_get_earliest: MagicMock, mock_update: MagicMock
) -> None:
    # Best-effort CP side: a control-plane error must neither raise nor lose the Django
    # write — the sensor keeps reading the Django row either way.
    _, team = _onboarded_team()
    mock_get_earliest.return_value = datetime(2020, 6, 15)
    mock_update.return_value = Response({"error": "boom"}, status=502)

    sync_team_earliest_event_date(team.id)

    assert DuckgresServerTeam.objects.get(team=team).earliest_event_date == date(2020, 6, 15)


@pytest.mark.django_db
@patch("products.data_warehouse.backend.presentation.views.managed_warehouse.update_team")
@patch("posthog.ducklake.common.get_earliest_event_date_for_team")
def test_sync_task_without_membership_row_is_a_noop(mock_get_earliest: MagicMock, mock_update: MagicMock) -> None:
    # A dispatch can race a deleted membership row — the task must skip quietly instead
    # of querying ClickHouse or pushing to the control plane for a de-onboarded team.
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)

    sync_team_earliest_event_date(team.id)

    mock_get_earliest.assert_not_called()
    mock_update.assert_not_called()
