import json
from typing import Any, cast

from unittest.mock import patch
import pytest
from django.test import override_settings
from parameterized import parameterized

from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.database.models import FieldTraverser, LazyJoin, StringDatabaseField, ExpressionField, Table
from posthog.hogql.errors import HogQLException
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.test.base import BaseTest
from posthog.warehouse.models import DataWarehouseTable, DataWarehouseCredential
from posthog.hogql.query import execute_hogql_query
from posthog.warehouse.models.join import DataWarehouseJoin


class TestDatabase(BaseTest):
    snapshot: Any

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_no_person_on_events(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            serialized_database = serialize_database(
                HogQLContext(team_id=self.team.pk, database=create_hogql_database(team_id=self.team.pk))
            )
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_with_person_on_events_enabled(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            serialized_database = serialize_database(
                HogQLContext(team_id=self.team.pk, database=create_hogql_database(team_id=self.team.pk))
            )
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @parameterized.expand([False, True])
    def test_can_select_from_each_table_at_all(self, poe_enabled: bool) -> None:
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=poe_enabled):
            serialized_database = serialize_database(
                HogQLContext(team_id=self.team.pk, database=create_hogql_database(team_id=self.team.pk))
            )
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
            f"SELECT whatever.id AS id FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s, %(hogql_val_1)s, %(hogql_val_2)s) AS whatever LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1",
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
            == "SELECT number AS number, expression AS expression, double AS double FROM (SELECT numbers.number AS number, plus(1, 1) AS expression, multiply(numbers.number, 2) AS double FROM numbers(2) AS numbers) LIMIT 10000"
        ), query

    def test_database_warehouse_joins(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="event",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = create_hogql_database(team_id=self.team.pk)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "select some_field.key from events"
        print_ast(parse_select(sql), context, dialect="clickhouse")

    def test_database_warehouse_joins_deleted_join(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="lower(event)",
            joining_table_name="groups",
            joining_table_key="upper(key)",
            field_name="some_field",
            deleted=True,
        )

        db = create_hogql_database(team_id=self.team.pk)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "select some_field.key from events"
        with pytest.raises(HogQLException):
            print_ast(parse_select(sql), context, dialect="clickhouse")

    def test_database_warehouse_joins_other_team(self):
        other_organization = Organization.objects.create(name="some_other_org")
        other_team = Team.objects.create(organization=other_organization)

        DataWarehouseJoin.objects.create(
            team=other_team,
            source_table_name="events",
            source_table_key="lower(event)",
            joining_table_name="groups",
            joining_table_key="upper(key)",
            field_name="some_field",
        )

        db = create_hogql_database(team_id=self.team.pk)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "select some_field.key from events"
        with pytest.raises(HogQLException):
            print_ast(parse_select(sql), context, dialect="clickhouse")

    def test_database_warehouse_joins_bad_key_expression(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="blah_de_blah(event)",
            joining_table_name="groups",
            joining_table_key="upper(key)",
            field_name="some_field",
        )

        create_hogql_database(team_id=self.team.pk)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_database_warehouse_joins_persons_no_poe(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = create_hogql_database(team_id=self.team.pk)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        pdi = cast(LazyJoin, db.events.fields["pdi"])
        pdi_persons_join = cast(LazyJoin, pdi.resolve_table(context).fields["person"])
        pdi_table = pdi_persons_join.resolve_table(context)

        assert pdi_table.fields["some_field"] is not None

        print_ast(parse_select("select person.some_field.key from events"), context, dialect="clickhouse")

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_database_warehouse_joins_persons_poe_v1(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = create_hogql_database(team_id=self.team.pk)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        poe = cast(Table, db.events.fields["poe"])

        assert poe.fields["some_field"] is not None

        print_ast(parse_select("select person.some_field.key from events"), context, dialect="clickhouse")

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_database_warehouse_joins_persons_poe_v2(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = create_hogql_database(team_id=self.team.pk)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        poe = cast(Table, db.events.fields["poe"])

        assert poe.fields["some_field"] is not None

        print_ast(parse_select("select person.some_field.key from events"), context, dialect="clickhouse")
