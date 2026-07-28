from datetime import date

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.ducklake import cp_teams, team_state
from posthog.models import Organization, Team


@pytest.fixture(autouse=True)
def _reset_cp_state():
    cp_teams.clear_cache()
    yield
    cp_teams.clear_cache()


def _team() -> tuple[Organization, Team]:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    return org, team


def _cp_row(team: Team, schema_name: str, **overrides) -> dict:
    row = {
        "org_id": str(team.organization_id),
        "team_id": team.id,
        "schema_name": schema_name,
        "enabled": True,
        "backfill_enabled": True,
        "events_table_name": None,
        "persons_table_name": None,
        "schema_data_imports_name": None,
        "earliest_event_date": None,
    }
    row.update(overrides)
    return row


def _patch_org_rows(rows):
    return patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=rows)


@pytest.mark.django_db
class TestDataImportsSchema:
    def test_resolves_from_cp_row(self) -> None:
        org, team = _team()
        with _patch_org_rows([_cp_row(team, "cp_schema")]):
            assert team_state.data_imports_schema(team.id) == "posthog_data_imports_cp_schema"

    def test_without_cp_row_falls_back_to_team_id_schema(self) -> None:
        org, team = _team()
        with _patch_org_rows([]):
            assert team_state.data_imports_schema(team.id) == f"posthog_data_imports_team_{team.id}"

    def test_raises_when_cp_unreachable_and_cache_cold(self) -> None:
        org, team = _team()
        with _patch_org_rows(None):
            with pytest.raises(team_state.CPUnavailableError):
                team_state.data_imports_schema(team.id)

    def test_serves_cached_rows_during_an_outage(self) -> None:
        org, team = _team()
        with _patch_org_rows([_cp_row(team, "cp_schema")]):
            team_state.data_imports_schema(team.id)
        with _patch_org_rows(None):
            assert team_state.data_imports_schema(team.id) == "posthog_data_imports_cp_schema"


@pytest.mark.django_db
class TestEventsPersonsTables:
    @parameterized.expand(
        [
            # Derive rule and pin precedence as served through the accessor.
            ("derived", {}, ("events_cp_schema", "persons_cp_schema")),
            (
                "grandfathered_shared_pins",
                {"events_table_name": "events", "persons_table_name": "persons"},
                ("events", "persons"),
            ),
        ]
    )
    def test_resolves_from_cp_row(self, _name: str, overrides: dict, expected: tuple[str, str]) -> None:
        org, team = _team()
        with _patch_org_rows([_cp_row(team, "cp_schema", **overrides)]):
            assert team_state.resolve_events_persons_tables(team.id) == expected

    def test_without_cp_row_falls_back_to_shared_tables(self) -> None:
        org, team = _team()
        with _patch_org_rows([]):
            assert team_state.resolve_events_persons_tables(team.id) == ("events", "persons")

    def test_raises_when_cp_unreachable_and_cache_cold(self) -> None:
        org, team = _team()
        with _patch_org_rows(None):
            with pytest.raises(team_state.CPUnavailableError):
                team_state.resolve_events_persons_tables(team.id)

    def test_rejects_an_unsafe_resolved_name(self) -> None:
        # Fail-closed SQL-safety: a CP row carrying a hostile identifier must never reach DDL.
        org, team = _team()
        with _patch_org_rows([_cp_row(team, "cp_schema", events_table_name="a;drop")]):
            with pytest.raises(ValueError):
                team_state.resolve_events_persons_tables(team.id)


@pytest.mark.django_db
class TestTeamBackfillState:
    @parameterized.expand(
        [
            ("onboarded_row_schema_is_suffix", {}, {"has_backfill": True, "table_suffix": "cp_schema"}),
            (
                "grandfathered_shared_row_has_no_suffix",
                {"events_table_name": "events", "persons_table_name": "persons"},
                {"has_backfill": True, "table_suffix": None},
            ),
        ]
    )
    def test_shapes(self, _name: str, overrides: dict, expected: dict) -> None:
        org, team = _team()
        with _patch_org_rows([_cp_row(team, "cp_schema", **overrides)]):
            assert team_state.team_backfill_state(team.id) == expected

    @parameterized.expand(
        [
            ("no_cp_row", []),
            # An unreachable CP must degrade to the not-onboarded shape, never 500 the status read.
            ("cp_unreachable", None),
        ]
    )
    def test_falls_back_to_not_onboarded(self, _name: str, rows) -> None:
        org, team = _team()
        with _patch_org_rows(rows):
            assert team_state.team_backfill_state(team.id) == {"has_backfill": False, "table_suffix": None}


@pytest.mark.django_db
class TestBackfillRowExists:
    @parameterized.expand(
        [
            ("cp_row_present", "present", True),
            ("cp_row_absent", "absent", False),
            # Fail closed: an unreachable CP must block a possibly-onboarded team's deletion.
            ("cp_unreachable_fails_closed", "unreachable", True),
        ]
    )
    def test_postures(self, _name: str, cp_state: str, expected: bool) -> None:
        org, team = _team()
        rows = {"present": [_cp_row(team, "cp_schema")], "absent": [], "unreachable": None}[cp_state]
        with _patch_org_rows(rows):
            assert team_state.backfill_row_exists(team.id, str(org.id)) is expected


@pytest.mark.django_db
class TestListEnabledBackfillRows:
    def test_returns_cp_rows_with_server_shim(self) -> None:
        org, team = _team()
        cp_rows = [_cp_row(team, "cp_schema", earliest_event_date="2020-06-15")]
        with patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=cp_rows):
            rows = team_state.list_enabled_backfill_rows("test")
        assert len(rows) == 1
        row = rows[0]
        assert row.team_id == team.id
        assert row.earliest_event_date == date(2020, 6, 15)
        # The sensors reach the org through the server FK; the CP row must mirror that shape.
        assert row.server.organization_id == str(org.id)

    def test_excludes_rows_with_backfill_disabled(self) -> None:
        org, team = _team()
        cp_rows = [_cp_row(team, "cp_schema", backfill_enabled=False)]
        with patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=cp_rows):
            assert team_state.list_enabled_backfill_rows("test") == []

    def test_returns_empty_without_raising_when_cp_down(self) -> None:
        with patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=None):
            assert team_state.list_enabled_backfill_rows("test") == []
