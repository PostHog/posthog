import os
from unittest.mock import patch
from dags.web_analytics_team_config import get_team_ids_from_sources

from posthog.models.web_preaggregated.team_config import (
    DEFAULT_ENABLED_TEAM_IDS,
    format_team_ids_for_sql,
    WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL,
)


def test_format_team_ids_for_sql_with_teams():
    team_ids = [1, 2, 3]
    result = format_team_ids_for_sql(team_ids)
    assert result == "team_id IN(1, 2, 3)"


def test_format_team_ids_for_sql_empty():
    team_ids = []
    result = format_team_ids_for_sql(team_ids)
    assert result == "1=1"


def test_format_team_ids_for_sql_none():
    result = format_team_ids_for_sql(None)
    assert result == "1=1"


def test_web_analytics_team_config_data_sql_with_default():
    sql = WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL()

    for team_id in DEFAULT_ENABLED_TEAM_IDS:
        assert str(team_id) in sql


def test_web_analytics_team_config_data_sql_with_custom_teams():
    custom_teams = [100, 200, 300]
    sql = WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL(custom_teams)

    for team_id in custom_teams:
        assert str(team_id) in sql

    for team_id in DEFAULT_ENABLED_TEAM_IDS:
        assert str(team_id) not in sql


def test_get_team_ids_from_sources_default():
    with patch.dict(os.environ, {}, clear=True):
        result = get_team_ids_from_sources()
        assert result == DEFAULT_ENABLED_TEAM_IDS


def test_get_team_ids_from_sources_with_env_var():
    env_teams = "100,200,300"
    with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": env_teams}):
        result = get_team_ids_from_sources()
        assert 100 in result
        assert 200 in result
        assert 300 in result


def test_get_team_ids_from_sources_combines_sources():
    env_teams = "100,200"
    with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": env_teams}):
        result = get_team_ids_from_sources()
        # Should include both env teams and default teams
        assert 100 in result
        assert 200 in result
        assert all(team in result for team in DEFAULT_ENABLED_TEAM_IDS)
