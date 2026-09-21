from datetime import date, datetime

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.data_warehouse.backend.tasks.tasks import sync_team_earliest_event_date
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)

TEAM_ID = 4242
ORGANIZATION_ID = "018f0000-0000-0000-0000-00000000c0de"


def _membership(earliest: date | None = None) -> ManagedWarehouseTeamMembership:
    return ManagedWarehouseTeamMembership(
        team_id=TEAM_ID,
        organization_id=ORGANIZATION_ID,
        schema_name="env",
        enabled=True,
        backfill_enabled=True,
        table_names=ManagedWarehouseTableNames(
            events_table="events_env",
            persons_table="persons_env",
            data_imports_schema="posthog_data_imports_env",
        ),
        earliest_event_date=earliest,
    )


def _patch_membership(row: ManagedWarehouseTeamMembership | None):
    return patch("products.data_warehouse.backend.tasks.tasks.get_org_team_membership", return_value=row)


@parameterized.expand(
    [
        ("pre_2015_clamped", datetime(2010, 3, 1), date(2015, 1, 1)),
        ("post_2015_kept", datetime(2020, 6, 15), date(2020, 6, 15)),
    ]
)
@patch("products.managed_warehouse.backend.facade.api.get_org_id_for_team", return_value=ORGANIZATION_ID)
@patch("products.managed_warehouse.backend.facade.api.update_team_earliest_event_date")
@patch("products.managed_warehouse.backend.facade.api.resolve_team_earliest_event_date")
def test_sync_task_resolves_and_pushes_to_control_plane(
    _name: str,
    earliest_dt: datetime | None,
    expected: date,
    mock_get_earliest: MagicMock,
    mock_update: MagicMock,
    _mock_org_id: MagicMock,
) -> None:
    # The provisioning-time task must apply the same clamp the backfill sensor uses and
    # persist the result on the team's duckgres control-plane row (the sensor's read source).
    mock_get_earliest.return_value = expected

    with _patch_membership(_membership()):
        sync_team_earliest_event_date(TEAM_ID)

    _mock_org_id.assert_called_once_with(TEAM_ID)
    mock_update.assert_called_once_with(ORGANIZATION_ID, TEAM_ID, expected)


@patch("products.managed_warehouse.backend.facade.api.get_org_id_for_team", return_value=ORGANIZATION_ID)
@patch("products.managed_warehouse.backend.facade.api.update_team_earliest_event_date")
@patch("products.managed_warehouse.backend.facade.api.resolve_team_earliest_event_date")
def test_sync_task_leaves_empty_team_unresolved(
    mock_get_earliest: MagicMock, mock_update: MagicMock, _mock_org_id: MagicMock
) -> None:
    # A just-provisioned project plausibly has no events YET. A cached date is final, so
    # storing the no-history sentinel here would permanently exclude the team from
    # historical backfill; the task must store nothing and leave the sensor to resolve
    # it later.
    mock_get_earliest.return_value = None

    with _patch_membership(_membership()):
        sync_team_earliest_event_date(TEAM_ID)

    mock_update.assert_not_called()


@patch("products.managed_warehouse.backend.facade.api.get_org_id_for_team", return_value=ORGANIZATION_ID)
@patch("products.managed_warehouse.backend.facade.api.update_team_earliest_event_date")
@patch("products.managed_warehouse.backend.facade.api.resolve_team_earliest_event_date")
def test_sync_task_skips_clickhouse_when_date_already_cached(
    mock_get_earliest: MagicMock, mock_update: MagicMock, _mock_org_id: MagicMock
) -> None:
    # Idempotent re-runs (dispatch retries, re-onboards) must not re-query ClickHouse or
    # re-push a date the control plane already holds.
    with _patch_membership(_membership(earliest=date(2019, 5, 1))):
        sync_team_earliest_event_date(TEAM_ID)

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
@patch("products.managed_warehouse.backend.facade.api.get_org_id_for_team", return_value=ORGANIZATION_ID)
@patch("products.managed_warehouse.backend.facade.api.update_team_earliest_event_date")
@patch("products.managed_warehouse.backend.facade.api.resolve_team_earliest_event_date")
def test_sync_task_is_a_noop_without_a_readable_row(
    _name: str, rows, mock_get_earliest: MagicMock, mock_update: MagicMock, _mock_org_id: MagicMock
) -> None:
    with _patch_membership(_membership() if rows else None):
        sync_team_earliest_event_date(TEAM_ID)

    mock_get_earliest.assert_not_called()
    mock_update.assert_not_called()
