import pytest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.data_warehouse.backend.max_tools import (
    HogQLQueryFixerTool,
    _get_schema_description,
    _get_system_prompt,
    _get_user_prompt,
)

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException


@pytest.mark.django_db
def test_get_schema_description(snapshot):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@test.com")

    query = "select * from events"
    database = Database.create_for(team=team, user=user)
    hogql_context = HogQLContext(team_id=team.id, user=user, enable_select_queries=True, database=database)

    res = _get_schema_description({"hogql_query": query}, hogql_context, database)

    assert res == snapshot


@pytest.mark.django_db
def test_get_system_prompt(snapshot):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    database = Database.create_for(team.id)
    all_table_names = database.get_all_table_names()

    res = _get_system_prompt(all_table_names)

    assert res == snapshot


@pytest.mark.django_db
def test_get_user_prompt(snapshot):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    query = "select * from events"
    database = Database.create_for(team.id)
    hogql_context = HogQLContext(team_id=team.id, enable_select_queries=True, database=database)

    schema_description = _get_schema_description({"hogql_query": query}, hogql_context, database)

    res = _get_user_prompt(schema_description)

    assert res == snapshot


def _fixer_and_context() -> tuple[HogQLQueryFixerTool, HogQLContext]:
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@test.com")
    database = Database.create_for(team=team, user=user)
    hogql_context = HogQLContext(team_id=team.id, user=user, enable_select_queries=True, database=database)
    tool = HogQLQueryFixerTool(team=team, user=user, tool_call_id="fix_hogql_query_tool_call_id")
    return tool, hogql_context


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "SELECT event, session.$session_duration FROM events WHERE {filters}",
        "SELECT event, session.$session_duration FROM events WHERE timestamp > {variables.from_date}",
        "SELECT event, session.$entry_current_url FROM events WHERE {filters} AND event = {variables.event_name}",
        "SELECT session_id FROM sessions WHERE $start_timestamp > {variables.from_date}",
        "SELECT count() FROM sessions WHERE {filters}",
        "WITH s AS (SELECT session_id FROM sessions WHERE {filters}) SELECT * FROM s",
        "SELECT event FROM events WHERE event IN (SELECT event FROM events WHERE {filters}) LIMIT {variables.limit}",
        "SELECT event FROM events WHERE {filters}",
        "SELECT event, session.$session_duration FROM events WHERE timestamp > {now()}",
        "SELECT session_id FROM sessions WHERE $start_timestamp > {now()}",
        "SELECT event, session.$entry_current_url FROM events WHERE event = {'$pageview'} AND {filters}",
    ],
)
def test_parse_output_accepts_query_with_placeholders(query):
    tool, hogql_context = _fixer_and_context()

    assert tool._parse_output({"query": f"{query};"}, hogql_context) == query


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "SELECT session.$session_duration, not_a_field FROM events WHERE {filters}",
        "SELECT session_id FROM not_a_table WHERE $start_timestamp > {variables.from_date}",
    ],
)
def test_parse_output_still_rejects_invalid_query_with_placeholders(query):
    tool, hogql_context = _fixer_and_context()

    with pytest.raises(PydanticOutputParserException) as exc_info:
        tool._parse_output({"query": query}, hogql_context)

    assert exc_info.value.llm_output == query
