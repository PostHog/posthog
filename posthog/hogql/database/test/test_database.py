import json
from typing import Any

from unittest.mock import patch
import pytest
from django.test import override_settings
from parameterized import parameterized

from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.database.models import FieldTraverser, StringDatabaseField, ExpressionField
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.test.base import BaseTest
from posthog.warehouse.models import DataWarehouseTable, DataWarehouseCredential
from posthog.hogql.query import execute_hogql_query


class TestDatabase(BaseTest):
    snapshot: Any

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_no_person_on_events(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_with_person_on_events_enabled(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @parameterized.expand([False, True])
    def test_can_select_from_each_table_at_all(self, poe_enabled: bool) -> None:
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=poe_enabled):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            for table, possible_columns in serialized_database.items():
                if table == "numbers":
                    execute_hogql_query(
                        "SELECT number FROM numbers(10) LIMIT 100",
                        self.team,
                        pretty=False,
                    )
                else:
                    columns = [
                        x["key"]
                        for x in possible_columns
                        if "table" not in x and "chain" not in x and "fields" not in x
                    ]
                    execute_hogql_query(
                        f"SELECT {','.join(columns)} FROM {table}",
                        team=self.team,
                        pretty=False,
                    )

    @patch("posthog.hogql.query.sync_execute", return_value=(None, None))
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_database_with_warehouse_tables(self, patch_execute):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            name="whatever",
            team=self.team,
            columns={"id": "String"},
            credential=credential,
            url_pattern="",
        )
        create_hogql_database(team_id=self.team.pk)

        response = execute_hogql_query(
            "select * from whatever",
            team=self.team,
            pretty=False,
        )

        self.assertEqual(
            response.clickhouse,
            f"SELECT whatever.id AS id FROM s3Cluster('posthog', %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s, %(hogql_val_1)s, %(hogql_val_2)s) AS whatever LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1",
        )

    def test_database_group_type_mappings(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="test", group_type_index=0)
        db = create_hogql_database(team_id=self.team.pk)

        assert db.events.fields["test"] == FieldTraverser(chain=["group_0"])

    def test_database_group_type_mappings_overwrite(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="event", group_type_index=0)
        db = create_hogql_database(team_id=self.team.pk)

        assert db.events.fields["event"] == StringDatabaseField(name="event")

    def test_database_expression_fields(self):
        db = create_hogql_database(team_id=self.team.pk)
        db.numbers.fields["expression"] = ExpressionField(name="expression", expr=parse_expr("1 + 1"))
        db.numbers.fields["double"] = ExpressionField(name="double", expr=parse_expr("number * 2"))
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        sql = "select number, double, expression + number from numbers(2)"
        query = print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            query
            == "SELECT numbers.number AS number, multiply(numbers.number, 2) AS double, plus(plus(1, 1), numbers.number) FROM numbers(2) AS numbers LIMIT 10000"
        ), query

        sql = "select double from (select double from numbers(2))"
        query = print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            query
            == "SELECT double AS double FROM (SELECT multiply(numbers.number, 2) AS double FROM numbers(2) AS numbers) LIMIT 10000"
        ), query

        # expression fields are not included in select *
        sql = "select * from (select * from numbers(2))"
        query = print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            query
            == "SELECT number AS number FROM (SELECT numbers.number AS number FROM numbers(2) AS numbers) LIMIT 10000"
        ), query
