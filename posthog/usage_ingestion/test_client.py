from posthog.usage_ingestion.client import team_is_enabled


def test_team_is_enabled_uses_source_specific_team_list(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_WAREHOUSE_ROWS_TEAMS", "2, 4")

    assert team_is_enabled("warehouse_rows", 2)
    assert team_is_enabled("warehouse_rows", 4)
    assert not team_is_enabled("warehouse_rows", 3)


def test_team_is_enabled_supports_all_teams(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_APM_TEAMS", "*")

    assert team_is_enabled("apm", 123)
