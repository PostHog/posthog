import pytest
from unittest.mock import Mock, patch

from langchain_core.runnables import RunnableConfig

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.data_warehouse.backend.hogql_fixer_ai import (
    HogQLQueryFixerTool,
    _get_schema_description,
    _get_system_prompt,
    _get_user_prompt,
)

from ee.hogai.utils.types import AssistantState


@pytest.mark.django_db
def test_get_schema_description(snapshot):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    query = "select * from events"
    database = create_hogql_database(team.id)
    hogql_context = HogQLContext(
        team_id=team.id,
        enable_select_queries=True,
        database=database,
        limit_top_select=False,
        readable_print=True,
    )

    res = _get_schema_description({"hogql_query": query}, hogql_context, database)

    assert res == snapshot


@pytest.mark.django_db
def test_get_system_prompt(snapshot):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    database = create_hogql_database(team.id)
    all_tables = database.get_all_tables()

    res = _get_system_prompt(all_tables)

    assert res == snapshot


@pytest.mark.django_db
def test_get_user_prompt(snapshot):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    query = "select * from events"
    database = create_hogql_database(team.id)
    hogql_context = HogQLContext(
        team_id=team.id,
        enable_select_queries=True,
        database=database,
        limit_top_select=False,
        readable_print=True,
    )

    schema_description = _get_schema_description({"hogql_query": query}, hogql_context, database)

    res = _get_user_prompt(schema_description)

    assert res == snapshot


@pytest.mark.django_db
def test_hogql_query_fixer_tool_removes_semicolons():
    """Test that HogQLQueryFixerTool properly removes semicolons from the end of queries."""
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@example.com")

    config: RunnableConfig = {
        "configurable": {
            "team": team,
            "user": user,
            "contextual_tools": {
                "fix_hogql_query": {"hogql_query": "SELECT count() FROM events;;;", "error_message": "Test error"}
            },
        },
    }

    with (
        patch("products.data_warehouse.backend.hogql_fixer_ai.ChatOpenAI") as mock_openai,
        patch("products.data_warehouse.backend.hogql_fixer_ai.parse_pydantic_structured_output") as mock_parse,
    ):
        # Mock the OpenAI response
        mock_model = Mock()
        mock_model.with_structured_output.return_value = mock_model
        mock_openai.return_value = mock_model

        # Mock the parse function to return a query with semicolons
        mock_parse_result = Mock()
        mock_parse_result.query = "SELECT count() FROM events;;;"
        mock_parse.return_value = lambda x: mock_parse_result

        tool = HogQLQueryFixerTool(team=team, user=user, state=AssistantState(messages=[]))

        result = tool._run(config=config)

        # The tool should remove semicolons and return a clean query
        assert result[0] is not None
        assert not result[0].endswith(";")
        assert "SELECT\n    count()\nFROM\n    events" == result[0]


@pytest.mark.django_db
def test_hogql_query_fixer_tool_fixes_function_names():
    """Test that HogQLQueryFixerTool properly removes semicolons from the end of queries."""
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@example.com")

    config: RunnableConfig = {
        "configurable": {
            "team": team,
            "user": user,
            "contextual_tools": {
                "fix_hogql_query": {
                    "hogql_query": "SELECT properties FROM events WHERE TOSTRING(properties.$os) = 'Mac OS' AND length({filters}) > 0 AND {custom_filter} OR {custom_filter_3} ORDER BY properties.$os ASC",
                    "error_message": "Test error",
                }
            },
        },
    }

    with (
        patch("products.data_warehouse.backend.hogql_fixer_ai.ChatOpenAI") as mock_openai,
        patch("products.data_warehouse.backend.hogql_fixer_ai.parse_pydantic_structured_output") as mock_parse,
    ):
        # Mock the OpenAI response
        mock_model = Mock()
        mock_model.with_structured_output.return_value = mock_model
        mock_openai.return_value = mock_model

        # Mock the parse function to return a query with semicolons
        mock_parse_result = Mock()
        mock_parse_result.query = "SELECT properties FROM events WHERE TOSTRING(properties.$os) = 'Mac OS' AND length({filters}) > 0 AND {custom_filter} OR {custom_filter_3} ORDER BY properties.$os ASC"
        mock_parse.return_value = lambda x: mock_parse_result

        tool = HogQLQueryFixerTool(team=team, user=user, state=AssistantState(messages=[]))

        result = tool._run(config=config)

        # The tool should remove semicolons and return a clean query
        assert result[0] is not None
        assert (
            "SELECT\n    properties\nFROM\n    events\nWHERE\n    toString(properties.$os) = 'Mac OS' AND length({filters}) > 0 AND {custom_filter} OR {custom_filter_3}\nORDER BY\n    properties.$os ASC"
            == result[0]
        )
