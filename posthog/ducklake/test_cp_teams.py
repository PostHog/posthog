from datetime import date

from unittest.mock import patch

from parameterized import parameterized

from posthog.ducklake import cp_teams
from posthog.ducklake.cp_teams import CPTeam, team_from_row


def _row(**overrides) -> dict:
    row = {
        "org_id": "org-1",
        "team_id": 1,
        "schema_name": "prod",
        "enabled": True,
        "backfill_enabled": True,
        "events_table_name": None,
        "persons_table_name": None,
        "schema_data_imports_name": None,
        "earliest_event_date": None,
    }
    row.update(overrides)
    return row


class TestCPTeamResolution:
    # The transitional derive rule must stay byte-identical to the django-suffix layout;
    # a premature switch to the future `<schema>.events` derivation (or broken pin
    # precedence) would point readers/writers at tables that don't exist.
    @parameterized.expand(
        [
            (
                "null_pins_derive_from_schema",
                {"schema_name": "us_prod"},
                ("events_us_prod", "persons_us_prod", "posthog_data_imports_us_prod"),
            ),
            (
                "pins_win_over_derivation",
                {
                    "schema_name": "team_7",
                    "events_table_name": "events",
                    "persons_table_name": "persons",
                    "schema_data_imports_name": "posthog_data_imports_team_7",
                },
                ("events", "persons", "posthog_data_imports_team_7"),
            ),
            (
                "partial_pins_mix_with_derivation",
                {"schema_name": "beta", "events_table_name": "events_legacy"},
                ("events_legacy", "persons_beta", "posthog_data_imports_beta"),
            ),
            (
                "empty_string_pins_are_treated_as_unset",
                {"schema_name": "beta", "events_table_name": "", "schema_data_imports_name": ""},
                ("events_beta", "persons_beta", "posthog_data_imports_beta"),
            ),
        ]
    )
    def test_resolved_names(self, _name: str, overrides: dict, expected: tuple[str, str, str]) -> None:
        team = team_from_row(_row(**overrides))
        assert team is not None
        assert (team.resolved_events_table, team.resolved_persons_table, team.resolved_data_imports_schema) == expected


class TestTeamFromRow:
    def test_coerces_types_defensively(self) -> None:
        # A CP that serializes team_id as a string must not break int comparisons, and the
        # date string must come back as a date so sensor math works.
        team = team_from_row(_row(team_id="42", earliest_event_date="2020-06-15", backfill_enabled=True))
        assert team == CPTeam(
            team_id=42,
            organization_id="org-1",
            schema_name="prod",
            enabled=True,
            backfill_enabled=True,
            events_table_name=None,
            persons_table_name=None,
            schema_data_imports_name=None,
            earliest_event_date=date(2020, 6, 15),
        )

    @parameterized.expand(
        [
            ("missing_team_id", {"team_id": None}),
            ("unparseable_team_id", {"team_id": "abc"}),
            ("missing_schema_name", {"schema_name": None}),
            # No org anywhere: a write would target /orgs//teams/... and fail silently.
            ("missing_org_id", {"org_id": None}),
        ]
    )
    def test_unusable_rows_are_dropped(self, _name: str, overrides: dict) -> None:
        assert team_from_row(_row(**overrides)) is None


class TestTTLCache:
    def setup_method(self) -> None:
        cp_teams.clear_cache()

    def teardown_method(self) -> None:
        cp_teams.clear_cache()

    def test_second_call_within_ttl_hits_cache(self) -> None:
        with patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=[_row()]) as mock_fetch:
            first = cp_teams.list_org_teams("org-1")
            second = cp_teams.list_org_teams("org-1")
        assert mock_fetch.call_count == 1
        assert first == second

    def test_clear_cache_forces_a_refetch(self) -> None:
        with patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=[_row()]) as mock_fetch:
            cp_teams.list_org_teams("org-1")
            cp_teams.clear_cache()
            cp_teams.list_org_teams("org-1")
        assert mock_fetch.call_count == 2

    def test_cache_is_keyed_per_org(self) -> None:
        with patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=[_row()]) as mock_fetch:
            cp_teams.list_org_teams("org-1")
            cp_teams.list_org_teams("org-2")
        assert mock_fetch.call_count == 2

    def test_failed_fetches_are_not_cached(self) -> None:
        # An outage must not poison the cache: the next call retries immediately.
        with patch("posthog.ducklake.cp_teams._fetch_org_rows", side_effect=[None, [_row()]]) as mock_fetch:
            assert cp_teams.list_org_teams("org-1") is None
            teams = cp_teams.list_org_teams("org-1")
        assert mock_fetch.call_count == 2
        assert teams is not None and teams[0].team_id == 1

    def test_expired_entry_is_refetched(self) -> None:
        with (
            patch("posthog.ducklake.cp_teams.CACHE_TTL_SECONDS", 0.0),
            patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=[_row()]) as mock_fetch,
        ):
            cp_teams.list_org_teams("org-1")
            cp_teams.list_org_teams("org-1")
        assert mock_fetch.call_count == 2

    def test_list_enabled_backfills_filters_disabled_rows(self) -> None:
        rows = [
            _row(team_id=1, backfill_enabled=True),
            _row(team_id=2, schema_name="two", backfill_enabled=False),
        ]
        with patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=rows):
            teams = cp_teams.list_enabled_backfills()
        assert teams is not None
        assert [team.team_id for team in teams] == [1]
