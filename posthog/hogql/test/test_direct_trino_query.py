from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import HogQLQueryExecutor

from posthog.schema_enums import InCohortVia, InlineCohortCalculation, PersonsOnEventsMode

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort
from products.data_warehouse.backend.direct_trino import DIRECT_TRINO_URL_PATTERN, get_direct_trino_table_options
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestDirectTrinoQuery(APIBaseTest):
    def _semantic_context(
        self,
        table_names: list[str],
        modifiers: HogQLQueryModifiers | None = None,
    ) -> HogQLContext:
        modifiers = modifiers or HogQLQueryModifiers()
        return HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            database=Database.create_for(
                self.team.pk,
                team=self.team,
                modifiers=modifiers,
                bypass_warehouse_access_control=True,
            ),
            modifiers=modifiers,
            enable_select_queries=True,
            limit_top_select=False,
            restricted_properties=set(),
            use_new_events_schema=False,
            apply_events_retention_floor=False,
            trino_table_locators={name: ("ducklake", "analytics", name) for name in table_names},
        )

    def _create_source_and_table(self) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.TRINO,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="analytics",
            job_inputs={
                "host": "trino.example.com",
                "port": 443,
                "catalog": "ducklake",
                "schema": "analytics",
                "auth_type": {"selection": "none", "user": "posthog"},
                "use_ssl": True,
                "verify_ssl": True,
            },
        )
        DataWarehouseTable.objects.create(
            name="orders",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            url_pattern=DIRECT_TRINO_URL_PATTERN,
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "status": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            },
            options=get_direct_trino_table_options(
                source_catalog="ducklake",
                source_schema="analytics",
                source_table_name="materialized_orders",
            ),
        )
        return source

    def test_query_editor_compiles_to_explicit_trino_relation(self) -> None:
        source = self._create_source_and_table()
        executor = HogQLQueryExecutor(
            query="SELECT ID FROM ORDERS WHERE STATUS = 'paid'",
            team=self.team,
            connection_id=str(source.id),
        )

        sql, context = executor.generate_clickhouse_sql()

        self.assertIn('"ducklake"."analytics"."materialized_orders"', sql)
        self.assertEqual(executor.direct_dialect, "trino")
        self.assertEqual(executor.direct_values, context.values)
        self.assertIn("paid", context.values.values())

    def test_action_semantics_expand_before_trino_printing(self) -> None:
        action = Action.objects.create(
            team=self.team,
            name="completed checkout",
            steps_json=[{"event": "checkout completed"}],
        )
        context = self._semantic_context(["events"])

        sql, _ = prepare_and_print_ast(
            parse_select(f"SELECT event FROM events WHERE matchesAction({action.pk})"),
            context,
            "trino",
        )

        self.assertNotIn("matchesAction", sql)
        self.assertIn('"ducklake"."analytics"."events"', sql)
        self.assertIn("checkout completed", context.values.values())

    def test_cohort_semantics_expand_before_trino_printing(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="active accounts")
        modifiers = HogQLQueryModifiers(
            inCohortVia=InCohortVia.SUBQUERY,
            inlineCohortCalculation=InlineCohortCalculation.OFF,
        )
        context = self._semantic_context(
            ["events", "raw_cohort_people", "raw_person_distinct_id_overrides"],
            modifiers,
        )

        sql, _ = prepare_and_print_ast(
            parse_select(f"SELECT person_id FROM events WHERE person_id IN COHORT {cohort.pk}"),
            context,
            "trino",
        )

        self.assertNotIn("COHORT", sql)
        self.assertIn('"ducklake"."analytics"."raw_cohort_people"', sql)

    def test_lazy_person_join_expands_before_trino_printing(self) -> None:
        modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        context = self._semantic_context(
            ["events", "raw_persons", "raw_person_distinct_ids", "raw_person_distinct_id_overrides"],
            modifiers,
        )

        sql, _ = prepare_and_print_ast(
            parse_select("SELECT person.properties.email FROM events"),
            context,
            "trino",
        )

        self.assertNotIn("person.properties.email", sql)
        self.assertIn('"ducklake"."analytics"."raw_persons"', sql)
        self.assertIn(" JOIN ", sql)

    @patch("posthog.hogql.direct_sql.trino_adapter.TrinoAdapter.validate_source_config")
    @patch("products.warehouse_sources.backend.facade.source_management.connect_trino")
    def test_query_editor_executes_compiled_values_as_driver_parameters(
        self, mock_connect_trino: MagicMock, mock_validate_source_config: MagicMock
    ) -> None:
        source = self._create_source_and_table()
        mock_validate_source_config.return_value = (MagicMock(), MagicMock())
        cursor = MagicMock()
        cursor.fetchmany.return_value = [(7,)]
        cursor.description = [("id", "bigint")]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        mock_connect_trino.return_value.__enter__.return_value = connection
        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders WHERE status = 'paid' LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        response = executor.execute()

        submitted_sql, submitted_values = cursor.execute.call_args.args
        self.assertIn('"ducklake"."analytics"."materialized_orders"', submitted_sql)
        self.assertIn("?", submitted_sql)
        self.assertNotIn("paid", submitted_sql)
        self.assertEqual(submitted_values, ["paid"])
        self.assertEqual(response.results, [(7,)])
