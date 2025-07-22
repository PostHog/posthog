import os
from unittest.mock import patch
from dags.web_analytics_team_config import get_team_ids_from_sources

from posthog.models.web_preaggregated.team_config import (
    DEFAULT_ENABLED_TEAM_IDS,
    WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL,
)


def test_web_analytics_team_config_data_sql_with_default():
    sql = WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL()

    for team_id in DEFAULT_ENABLED_TEAM_IDS:
        assert str(team_id) in sql


def test_web_analytics_team_config_data_sql_with_custom_teams():
    custom_teams = [100, 200, 300]
    sql = WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL(custom_teams)

    for team_id in custom_teams:
        assert str(team_id) in sql

    # Check that default team IDs are not in the VALUES section
    values_section = sql.split("VALUES")[1] if "VALUES" in sql else sql
    for team_id in DEFAULT_ENABLED_TEAM_IDS:
        assert f"({team_id}," not in values_section


def test_get_team_ids_from_sources_default():
    with patch.dict(os.environ, {}, clear=True):
        result = get_team_ids_from_sources()
        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)


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
