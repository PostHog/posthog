from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import ExpressionField
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.data_tools.backend.models.expression import DataWarehouseExpression
from products.data_warehouse.backend.presentation.views.expression import DataWarehouseExpressionSerializer


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
            ("unknown_table", "not_a_table", "browser", "properties.$browser"),
            ("syntax_error", "events", "browser", "properties.$browser +"),
            ("unknown_column", "events", "browser", "upper(nonexistent_column)"),
            ("empty_expression", "events", "browser", ""),
        ]
    )
    def test_invalid_input_rejected(self, _name, table_name, field_name, expression):
        response = self._create(table_name=table_name, field_name=field_name, expression=expression)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(DataWarehouseExpression.objects.for_team(self.team.pk).count(), 0)

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

    def test_connection_scoped_expression_stays_out_of_default_database(self):
        with team_scope(self.team.pk):
            DataWarehouseExpression.objects.create(
                team=self.team,
                table_name="events",
                field_name="scoped_field",
                expression="upper(event)",
                connection_id=uuid4(),
            )

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
