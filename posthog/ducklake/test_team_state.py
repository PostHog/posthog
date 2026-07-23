from datetime import date

import pytest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.ducklake import cp_teams, team_state
from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam
from posthog.models import Organization, Team


@pytest.fixture(autouse=True)
def _reset_cp_state():
    cp_teams.clear_cache()
    team_state.clear_parity_state()
    yield
    cp_teams.clear_cache()
    team_state.clear_parity_state()


def _onboarded_team(table_suffix: str | None = "prod") -> tuple[Organization, Team]:
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    server = DuckgresServer.objects.create(
        organization=org, host="h", port=5432, database="ducklake", username="root", password="x"
    )
    DuckgresServerTeam.objects.create(server=server, team=team, table_suffix=table_suffix)
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
class TestDataImportsSchemaRouting:
    @parameterized.expand(
        [
            # django (the default) must serve the django value even when the CP disagrees —
            # flipping reads is opt-in, never a side effect of a CP edit.
            ("django", "posthog_data_imports_prod"),
            ("dual", "posthog_data_imports_prod"),
            ("cp", "posthog_data_imports_cp_schema"),
        ]
    )
    def test_mode_selects_the_read_source(self, source: str, expected: str) -> None:
        org, team = _onboarded_team(table_suffix="prod")
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE=source),
            _patch_org_rows([_cp_row(team, "cp_schema")]),
        ):
            assert team_state.data_imports_schema(team.id) == expected

    def test_cp_mode_without_cp_row_falls_back_to_team_id_schema(self) -> None:
        org, team = _onboarded_team()
        with override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"), _patch_org_rows([]):
            assert team_state.data_imports_schema(team.id) == f"posthog_data_imports_team_{team.id}"

    def test_cp_mode_raises_when_cp_unreachable_and_cache_cold(self) -> None:
        org, team = _onboarded_team()
        with override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"), _patch_org_rows(None):
            with pytest.raises(team_state.CPUnavailableError):
                team_state.data_imports_schema(team.id)

    def test_cp_mode_serves_cached_rows_during_an_outage(self) -> None:
        org, team = _onboarded_team()
        with override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"):
            with _patch_org_rows([_cp_row(team, "cp_schema")]):
                team_state.data_imports_schema(team.id)
            with _patch_org_rows(None):
                assert team_state.data_imports_schema(team.id) == "posthog_data_imports_cp_schema"

    def test_django_mode_never_touches_the_control_plane(self) -> None:
        org, team = _onboarded_team()
        with patch("posthog.ducklake.cp_teams._fetch_org_rows") as mock_fetch:
            team_state.data_imports_schema(team.id)
        mock_fetch.assert_not_called()


@pytest.mark.django_db
class TestDualModeParityTelemetry:
    def test_mismatch_emits_counter_and_rate_limited_log(self) -> None:
        org, team = _onboarded_team(table_suffix="prod")
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="dual"),
            _patch_org_rows([_cp_row(team, "other")]),
            patch("statshog.defaults.django.statsd") as mock_statsd,
            patch.object(team_state.logger, "warning") as mock_warning,
        ):
            assert team_state.data_imports_schema(team.id) == "posthog_data_imports_prod"
            # Second call within the TTL window: counted again, but not logged again.
            team_state.data_imports_schema(team.id)

        counters = [call.args[0] for call in mock_statsd.incr.call_args_list]
        assert counters.count(team_state.PARITY_CHECKS_COUNTER) == 2
        assert counters.count(team_state.PARITY_MISMATCH_COUNTER) == 2
        mismatch_logs = [
            call for call in mock_warning.call_args_list if call.args[0] == "duckgres_team_state_parity_mismatch"
        ]
        assert len(mismatch_logs) == 1
        assert mismatch_logs[0].kwargs == {
            "team_id": team.id,
            "field": "data_imports_schema",
            "django_value": "posthog_data_imports_prod",
            "cp_value": "posthog_data_imports_other",
            "call_site": "data_imports_schema",
        }

    def test_agreement_emits_check_but_no_mismatch(self) -> None:
        org, team = _onboarded_team(table_suffix="prod")
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="dual"),
            _patch_org_rows([_cp_row(team, "prod")]),
            patch("statshog.defaults.django.statsd") as mock_statsd,
        ):
            assert team_state.data_imports_schema(team.id) == "posthog_data_imports_prod"
        counters = [call.args[0] for call in mock_statsd.incr.call_args_list]
        assert team_state.PARITY_CHECKS_COUNTER in counters
        assert team_state.PARITY_MISMATCH_COUNTER not in counters

    def test_cp_unavailable_serves_django_and_counts_distinctly(self) -> None:
        org, team = _onboarded_team(table_suffix="prod")
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="dual"),
            _patch_org_rows(None),
            patch("statshog.defaults.django.statsd") as mock_statsd,
            patch.object(team_state.logger, "warning") as mock_warning,
        ):
            assert team_state.data_imports_schema(team.id) == "posthog_data_imports_prod"
        counters = [call.args[0] for call in mock_statsd.incr.call_args_list]
        assert counters == [team_state.PARITY_CP_UNAVAILABLE_COUNTER]
        assert not any(call.args[0] == "duckgres_team_state_parity_mismatch" for call in mock_warning.call_args_list)


@pytest.mark.django_db
class TestEventsPersonsTablesRouting:
    @parameterized.expand(
        [
            # Derive rule and pin precedence as served through the accessor in cp mode.
            ("derived", {}, ("events_cp_schema", "persons_cp_schema")),
            (
                "grandfathered_shared_pins",
                {"events_table_name": "events", "persons_table_name": "persons"},
                ("events", "persons"),
            ),
        ]
    )
    def test_cp_mode_resolves_from_cp_row(self, _name: str, overrides: dict, expected: tuple[str, str]) -> None:
        org, team = _onboarded_team()
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"),
            _patch_org_rows([_cp_row(team, "cp_schema", **overrides)]),
        ):
            assert team_state.resolve_events_persons_tables(team.id) == expected

    def test_cp_mode_without_cp_row_falls_back_to_shared_tables(self) -> None:
        org, team = _onboarded_team()
        with override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"), _patch_org_rows([]):
            assert team_state.resolve_events_persons_tables(team.id) == ("events", "persons")

    def test_cp_mode_rejects_an_unsafe_resolved_name(self) -> None:
        # Fail-closed SQL-safety: a CP row carrying a hostile identifier must never reach DDL.
        org, team = _onboarded_team()
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"),
            _patch_org_rows([_cp_row(team, "cp_schema", events_table_name="a;drop")]),
        ):
            with pytest.raises(ValueError):
                team_state.resolve_events_persons_tables(team.id)

    def test_django_mode_uses_the_suffix(self) -> None:
        org, team = _onboarded_team(table_suffix="prod")
        assert team_state.resolve_events_persons_tables(team.id) == ("events_prod", "persons_prod")


@pytest.mark.django_db
class TestTeamBackfillStateRouting:
    @parameterized.expand(
        [
            ("dual_write_row_schema_is_suffix", {}, {"has_backfill": True, "table_suffix": "cp_schema"}),
            (
                "grandfathered_shared_row_has_no_suffix",
                {"events_table_name": "events", "persons_table_name": "persons"},
                {"has_backfill": True, "table_suffix": None},
            ),
        ]
    )
    def test_cp_mode_shapes(self, _name: str, overrides: dict, expected: dict) -> None:
        org, team = _onboarded_team()
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"),
            _patch_org_rows([_cp_row(team, "cp_schema", **overrides)]),
        ):
            assert team_state.team_backfill_state(team.id) == expected

    @parameterized.expand(
        [
            ("no_cp_row", []),
            # An unreachable CP must degrade to the not-onboarded shape, never 500 the status read.
            ("cp_unreachable", None),
        ]
    )
    def test_cp_mode_falls_back_to_not_onboarded(self, _name: str, rows) -> None:
        org, team = _onboarded_team()
        with override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"), _patch_org_rows(rows):
            assert team_state.team_backfill_state(team.id) == {"has_backfill": False, "table_suffix": None}

    def test_dual_mode_serves_django_and_flags_divergence(self) -> None:
        org, team = _onboarded_team(table_suffix="prod")
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="dual"),
            _patch_org_rows([]),
            patch("statshog.defaults.django.statsd") as mock_statsd,
        ):
            assert team_state.team_backfill_state(team.id) == {"has_backfill": True, "table_suffix": "prod"}
        counters = [call.args[0] for call in mock_statsd.incr.call_args_list]
        assert team_state.PARITY_MISMATCH_COUNTER in counters


@pytest.mark.django_db
class TestBackfillRowExistsRouting:
    @parameterized.expand(
        [
            ("cp_row_present", "present", True),
            ("cp_row_absent", "absent", False),
            # Fail closed: an unreachable CP must block a possibly-onboarded team's deletion.
            ("cp_unreachable_fails_closed", "unreachable", True),
        ]
    )
    def test_cp_mode(self, _name: str, cp_state: str, expected: bool) -> None:
        org, team = _onboarded_team()
        rows = {"present": [_cp_row(team, "cp_schema")], "absent": [], "unreachable": None}[cp_state]
        with override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"), _patch_org_rows(rows):
            assert team_state.backfill_row_exists(team.id, str(org.id)) is expected

    def test_dual_mode_serves_django(self) -> None:
        org, team = _onboarded_team()
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="dual"),
            _patch_org_rows([]),
            patch("statshog.defaults.django.statsd"),
        ):
            assert team_state.backfill_row_exists(team.id, str(org.id)) is True


@pytest.mark.django_db
class TestListEnabledBackfillRows:
    def test_django_mode_returns_model_rows(self) -> None:
        org, team = _onboarded_team()
        rows = team_state.list_enabled_backfill_rows("test")
        assert [row.team_id for row in rows] == [team.id]
        assert isinstance(rows[0], DuckgresServerTeam)

    def test_cp_mode_returns_cp_rows_with_server_shim(self) -> None:
        org, team = _onboarded_team()
        cp_rows = [_cp_row(team, "cp_schema", earliest_event_date="2020-06-15")]
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"),
            patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=cp_rows),
        ):
            rows = team_state.list_enabled_backfill_rows("test")
        assert len(rows) == 1
        row = rows[0]
        assert row.team_id == team.id
        assert row.earliest_event_date == date(2020, 6, 15)
        # The sensors reach the org through the server FK; the CP row must mirror that shape.
        assert row.server.organization_id == str(org.id)

    def test_cp_mode_returns_empty_without_raising_when_cp_down(self) -> None:
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="cp"),
            patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=None),
        ):
            assert team_state.list_enabled_backfill_rows("test") == []

    def test_dual_mode_flags_membership_and_date_divergence(self) -> None:
        org, team = _onboarded_team()
        cp_rows = [_cp_row(team, "cp_schema", earliest_event_date="2020-06-15"), _cp_row(team, "x", team_id=999_999)]
        with (
            override_settings(DUCKGRES_TEAM_STATE_SOURCE="dual"),
            patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=cp_rows),
            patch("statshog.defaults.django.statsd") as mock_statsd,
        ):
            rows = team_state.list_enabled_backfill_rows("test")
        # Django rows are served untouched.
        assert [row.team_id for row in rows] == [team.id]
        assert isinstance(rows[0], DuckgresServerTeam)
        # Two mismatches: the django row's earliest date differs, and the CP-only team 999999.
        counters = [call.args[0] for call in mock_statsd.incr.call_args_list]
        assert counters.count(team_state.PARITY_MISMATCH_COUNTER) == 2
