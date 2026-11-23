import pytest

from django.test import override_settings

from posthog.settings.ingestion import parse_ai_events_retention_days_by_team

from products.ai_observability.backend.logic.ai_events_retention import ai_events_retention_days


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", {}),
        ("1:60", {1: 60}),
        ("1:90", {1: 90}),
        ("1:90, 2:365", {1: 90, 2: 365}),
        ("1:30,2:365", {1: 30, 2: 365}),
    ],
)
def test_parses_retention_days_by_team(raw, expected):
    assert parse_ai_events_retention_days_by_team(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1:29,2:90",
        "1:366,2:90",
        "1:120,2:90",
        "1:abc,2:90",
        "x:90,2:90",
        "1,2:90",
        "1:90.5,2:90",
        "-1:90,2:90",
        "1:90:120,2:90",
        "2:90,",
        "2:90,2:120",
    ],
)
def test_skips_an_invalid_entry_and_keeps_the_rest(raw):
    assert parse_ai_events_retention_days_by_team(raw) == {2: 90}


@pytest.mark.parametrize("team_id,expected", [(7, 90), (8, 30)])
def test_retention_days_for_a_team(team_id, expected):
    with override_settings(AI_EVENTS_RETENTION_DAYS_BY_TEAM=parse_ai_events_retention_days_by_team("7:90")):
        assert ai_events_retention_days(team_id) == expected
