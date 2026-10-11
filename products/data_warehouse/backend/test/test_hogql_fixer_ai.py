import pytest
from unittest import mock

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import NotImplementedError as HogQLNotImplementedError

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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query,patch_target,side_effect,expected_error",
    [
        ("select event from events", None, None, None),
        (
            "select JSONExtract(properties.tags, 'Array(String)') from events",
            None,
            None,
            "cannot be inside Nullable type",
        ),
        (
            "select event from events",
            "prepare_and_print_ast",
            HogQLNotImplementedError("Unsupported node"),
            "Unsupported node",
        ),
        ("select event from events", "sync_execute", ConnectionError("ClickHouse unavailable"), None),
    ],
    ids=["valid", "clickhouse_type_error", "internal_hogql_error", "clickhouse_unavailable"],
)
def test_parse_output_validates_candidate(query, patch_target, side_effect, expected_error):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)
    user = User.objects.create(email="test@test.com")
    tool = HogQLQueryFixerTool(team=team, user=user)
    hogql_context = HogQLContext(
        team=team, user=user, enable_select_queries=True, database=Database.create_for(team=team, user=user)
    )

    with mock.patch(
        f"products.data_warehouse.backend.max_tools.{patch_target or 'capture_exception'}", side_effect=side_effect
    ):
        if expected_error is None:
            assert tool._parse_output({"query": query}, hogql_context) == query
        else:
            with pytest.raises(PydanticOutputParserException) as exc_info:
                tool._parse_output({"query": query}, hogql_context)
            assert expected_error in exc_info.value.validation_message
