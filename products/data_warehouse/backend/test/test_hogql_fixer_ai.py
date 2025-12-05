import pytest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.data_warehouse.backend.hogql_fixer_ai import _get_schema_description, _get_system_prompt, _get_user_prompt


@pytest.mark.django_db
def test_get_schema_description(snapshot):
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    query = "select * from events"
    database = Database.create_for(team.id)
    hogql_context = HogQLContext(team_id=team.id, enable_select_queries=True, database=database)

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
