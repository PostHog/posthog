import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async

from posthog.hogql import ast

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.temporal.messaging.hogql_compile import compile_hogql_for_streaming


@pytest.mark.django_db
class TestCompileHogqlForStreaming:
    @pytest.mark.asyncio
    async def test_bypasses_property_restrictions(self):
        """restricted_properties=set() must skip get_restricted_properties_for_team."""
        organization = await sync_to_async(Organization.objects.create)(name="Test Organization")
        team = await sync_to_async(Team.objects.create)(name="Test Team", organization=organization)

        node = ast.SelectQuery(
            select=[ast.Alias(alias="person_id", expr=ast.Field(chain=["id"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        )

        with patch(
            "posthog.hogql.printer.utils.get_restricted_properties_for_team",
            side_effect=AssertionError("get_restricted_properties_for_team must not be called"),
        ):
            sql, params = await compile_hogql_for_streaming(node, team_id=team.id)

        assert "FORMAT JSONEachRow" in sql

    @pytest.mark.asyncio
    async def test_property_key_is_parameterized(self):
        """Property keys must reach ClickHouse as parameters, not as unquoted SQL fragments.

        When the ``persons`` lazy table is used, HogQL generates a subquery that references the
        property via ``JSONExtractRaw(person.properties, %(hogql_val_N)s, ...)`` with the key as
        a parameter, and also as a backtick-quoted column alias. The backtick quoting makes the
        key inert as a SQL identifier — ClickHouse treats it as a column name, not executable code.
        What must never happen is the key appearing as an unquoted SQL string or code fragment.
        """
        organization = await sync_to_async(Organization.objects.create)(name="Test Organization")
        team = await sync_to_async(Team.objects.create)(name="Test Team", organization=organization)

        prop_key = "email') UNION ALL SELECT sleep(3) --"
        node = ast.SelectQuery(
            select=[
                ast.Alias(alias="person_id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="prop_0", expr=ast.Field(chain=["properties", prop_key])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        )

        sql, params = await compile_hogql_for_streaming(node, team_id=team.id)

        # The prop key must appear in the params dict (for the JSONExtractRaw call).
        assert prop_key in params.values()
        # The prop key must not appear as an unquoted SQL fragment — any occurrence must be
        # inside backtick-quoted identifiers, which ClickHouse treats as column names.
        assert f"'{prop_key}'" not in sql  # not a SQL string literal
        assert f'"{prop_key}"' not in sql  # not a double-quoted identifier
        assert "UNION ALL SELECT sleep" not in sql.split("`")[::2]  # not outside backtick pairs
        assert "FORMAT JSONEachRow" in sql
