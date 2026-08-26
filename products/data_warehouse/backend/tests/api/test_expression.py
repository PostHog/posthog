from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.data_tools.backend.models.expression import DataWarehouseExpression
from products.data_warehouse.backend.presentation.views.expression import (
    MAX_EXPRESSION_LENGTH,
    DataWarehouseExpressionSerializer,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


class TestExpressionApi(APIBaseTest):
    def _create(self, table_name="events", field_name="browser", expression="properties.$browser"):
        return self.client.post(
            f"/api/environments/{self.team.id}/warehouse_expressions/",
            {"table_name": table_name, "field_name": field_name, "expression": expression},
        )

    def _database(self) -> Database:
        return Database.create_for(team_id=self.team.pk, user=self.user)

    def test_create_injects_field_usable_in_queries(self):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["table_name"], "events")
        self.assertEqual(data["field_name"], "browser")
        self.assertEqual(data["expression"], "properties.$browser")

        database = self._database()
        field = database.get_table("events").fields.get("browser")
        self.assertIsInstance(field, ExpressionField)

        context = HogQLContext(team_id=self.team.pk, database=database, enable_select_queries=True)
        printed, _ = prepare_and_print_ast(parse_select("SELECT browser FROM events"), context, "clickhouse")
        self.assertIn("JSONExtractRaw(events.properties", printed)
        self.assertIn("$browser", context.values.values())

    @parameterized.expand(
        [
            ("override_existing_field", "events", "event", "properties.$browser"),
            ("field_name_with_period", "events", "my.field", "properties.$browser"),
            # "*" resolves as a wildcard, so if it were saved it would smuggle a bare star
            # into every teammate's SELECT * and expose hidden physical columns.
            ("field_name_star", "events", "*", "properties.$browser"),
            ("field_name_with_backtick", "events", "bro`wser", "properties.$browser"),
            ("unknown_table", "not_a_table", "browser", "properties.$browser"),
            ("syntax_error", "events", "browser", "properties.$browser +"),
            ("unknown_column", "events", "browser", "upper(nonexistent_column)"),
            ("empty_expression", "events", "browser", ""),
            ("expression_too_long", "events", "browser", "1 + " + "1" * MAX_EXPRESSION_LENGTH),
        ]
    )
    def test_invalid_input_rejected(self, _name, table_name, field_name, expression):
        response = self._create(table_name=table_name, field_name=field_name, expression=expression)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(DataWarehouseExpression.objects.for_team(self.team.pk).count(), 0)

    def test_per_team_count_cap(self):
        with patch(
            "products.data_warehouse.backend.presentation.views.expression.MAX_EXPRESSIONS_PER_TEAM",
            1,
        ):
            self.assertEqual(self._create().status_code, 201)
            response = self._create(field_name="os", expression="properties.$os")
            self.assertEqual(response.status_code, 400, response.content)

            # Soft-deleted rows don't count toward the cap on create, and restoring one
            # past the cap must be blocked too - otherwise create-deleted-then-restore
            # bypasses the limit entirely.
            deleted_response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_expressions/",
                {"table_name": "events", "field_name": "os", "expression": "properties.$os", "deleted": True},
            )
            self.assertEqual(deleted_response.status_code, 201, deleted_response.content)
            restore_url = f"/api/environments/{self.team.id}/warehouse_expressions/{deleted_response.json()['id']}/"
            self.assertEqual(self.client.patch(restore_url, {"deleted": False}).status_code, 400)

            # Restoring is fine once the team is back under the cap.
            active_id = DataWarehouseExpression.objects.for_team(self.team.pk).get(deleted=False).id
            self.client.delete(f"/api/environments/{self.team.id}/warehouse_expressions/{active_id}/")
            self.assertEqual(self.client.patch(restore_url, {"deleted": False}).status_code, 200)

    def test_mutually_recursive_expressions_fail_as_query_error(self):
        # Bypasses API validation the way a concurrent-save race would: each expression was
        # validated against a database that didn't yet contain the other.
        with team_scope(self.team.pk):
            DataWarehouseExpression.objects.create(
                team=self.team, table_name="events", field_name="field_a", expression="field_b"
            )
            DataWarehouseExpression.objects.create(
                team=self.team, table_name="events", field_name="field_b", expression="field_a"
            )

        context = HogQLContext(team_id=self.team.pk, database=self._database(), enable_select_queries=True)
        with self.assertRaises(QueryError):
            prepare_and_print_ast(parse_select("SELECT field_a FROM events"), context, "clickhouse")

    def test_duplicate_field_name_rejected(self):
        self.assertEqual(self._create().status_code, 201)
        response = self._create(expression="properties.$os")
        self.assertEqual(response.status_code, 400, response.content)

    def test_losing_duplicate_race_surfaces_as_validation_error(self):
        self.assertEqual(self._create().status_code, 201)

        # Calling create() directly skips validate()'s duplicate check, like a request that
        # passed validation concurrently and lost the race to the unique constraint.
        serializer = DataWarehouseExpressionSerializer(
            context={"team_id": self.team.pk, "request": SimpleNamespace(user=self.user)}
        )
        with team_scope(self.team.pk), self.assertRaises(DRFValidationError):
            serializer.create({"table_name": "events", "field_name": "browser", "expression": "1"})

    def test_update_changes_expression_and_rejects_self_reference(self):
        expression_id = self._create().json()["id"]

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_expressions/{expression_id}/",
            {"expression": "upper(properties.$os)"},
        )
        self.assertEqual(response.status_code, 200, response.content)

        database = self._database()
        field = database.get_table("events").fields["browser"]
        assert isinstance(field, ExpressionField)
        self.assertEqual(field.expr.to_hogql(), "upper(properties.$os)")

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_expressions/{expression_id}/",
            {"expression": "upper(browser)"},
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_soft_delete_removes_field(self):
        expression_id = self._create().json()["id"]

        response = self.client.delete(f"/api/environments/{self.team.id}/warehouse_expressions/{expression_id}/")
        self.assertEqual(response.status_code, 204, response.content)

        self.assertNotIn("browser", self._database().get_table("events").fields)
        self.assertEqual(
            self.client.get(f"/api/environments/{self.team.id}/warehouse_expressions/").json()["results"], []
        )
        expression = DataWarehouseExpression.objects.for_team(self.team.pk).get(id=expression_id)
        self.assertTrue(expression.deleted)

    def test_activity_log_records_who_did_what(self):
        expression_id = self._create().json()["id"]
        self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_expressions/{expression_id}/",
            {"expression": "upper(properties.$os)"},
        )
        self.client.delete(f"/api/environments/{self.team.id}/warehouse_expressions/{expression_id}/")

        logs = list(
            ActivityLog.objects.filter(team_id=self.team.pk, scope="DataWarehouseExpression", item_id=expression_id)
            .order_by("created_at")
            .values_list("activity", "user__email", "detail__name")
        )
        self.assertEqual(
            logs,
            [
                ("created", self.user.email, "events.browser"),
                ("updated", self.user.email, "events.browser"),
                ("deleted", self.user.email, "events.browser"),
            ],
        )

    @parameterized.expand(
        [
            (
                "postgres",
                "Postgres",
                {
                    "host": "localhost",
                    "port": 5432,
                    "database": "postgres",
                    "user": "postgres",
                    "password": "postgres",
                    "schema": "public",
                },
            ),
            (
                "clickhouse",
                "ClickHouse",
                {
                    "host": "localhost",
                    "port": 8443,
                    "database": "posthog",
                    "user": "default",
                    "password": "password",
                },
            ),
        ]
    )
    def test_connection_scoped_expression_saves_in_source_dialect(
        self, _name: str, source_type: str, job_inputs: dict[str, object]
    ) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="direct",
            job_inputs=job_inputs,
        )
        DataWarehouseTable.objects.create(
            name="events",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "team_id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
            },
        )

        create_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_expressions/",
            {
                "table_name": "events",
                "field_name": "scoped_field",
                "expression": "id + 1",
                "connection_id": str(source.id),
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.content)

        expression_id = create_response.json()["id"]
        update_response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_expressions/{expression_id}/",
            {"expression": "id + 2"},
        )
        self.assertEqual(update_response.status_code, 200, update_response.content)
        self.assertEqual(update_response.json()["expression"], "id + 2")

        direct_database = Database.create_for(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
        )
        field = direct_database.get_table("events").fields["scoped_field"]
        assert isinstance(field, ExpressionField)
        self.assertNotIn("scoped_field", self._database().get_table("events").fields)

    def test_stale_expression_degrades_instead_of_breaking_schema(self):
        # Bypasses API validation the way a valid expression goes stale in real life: the
        # referenced column exists at save time and disappears later.
        with team_scope(self.team.pk):
            DataWarehouseExpression.objects.create(
                team=self.team, table_name="events", field_name="broken", expression="upper(gone_column)"
            )

        database = self._database()
        self.assertIsInstance(database.get_table("events").fields.get("broken"), ExpressionField)

        context = HogQLContext(team_id=self.team.pk, database=database)
        serialized = database.serialize(context)
        self.assertIn("broken", serialized["events"].fields)
