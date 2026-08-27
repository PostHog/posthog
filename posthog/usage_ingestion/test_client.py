from posthog.usage_ingestion.client import _timeout_seconds, team_is_enabled


def test_team_is_enabled_uses_the_shared_team_list(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "2, 4")

    assert team_is_enabled(2)
    assert team_is_enabled(4)
    assert not team_is_enabled(3)


def test_team_is_enabled_supports_all_teams(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "*")

    assert team_is_enabled(123)


def test_timeout_converts_milliseconds_to_the_seconds_grpc_expects(monkeypatch) -> None:
    monkeypatch.delenv("USAGE_INGESTION_TIMEOUT_MS", raising=False)
    assert _timeout_seconds() == 5.0

    monkeypatch.setenv("USAGE_INGESTION_TIMEOUT_MS", "250")
    assert _timeout_seconds() == 0.25
