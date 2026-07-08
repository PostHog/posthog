from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import DatabaseError
from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    HogLanguage,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLQuery,
    HogQLQueryModifiers,
    SessionTableVersion,
)

from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.parser import parse_select

from posthog.models import EventDefinition, PropertyDefinition

from products.cohorts.backend.models.cohort import Cohort
from products.product_analytics.backend.models.insight_variable import InsightVariable
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestMetadata(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None
    # No test here writes per-team ClickHouse data, so the per-test team isolation
    # that ClickhouseTestMixin defaults to (CLASS_DATA_LEVEL_SETUP = False) only adds
    # ~100ms of org/team/user creation to every test.
    CLASS_DATA_LEVEL_SETUP = True

    def _expr(self, query: str, table: str = "events", debug=True) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL_EXPR,
                query=query,
                sourceQuery=HogQLQuery(query=f"select * from {table}"),
                response=None,
                debug=debug,
            ),
            team=self.team,
        )

    def _select(self, query: str, modifiers: Optional[HogQLQueryModifiers] = None) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata", language=HogLanguage.HOG_QL, query=query, response=None, modifiers=modifiers
            ),
            team=self.team,
        )

    def _select_with_variables(
        self, query: str, variables: Optional[dict[str, dict]] = None, globals: Optional[dict] = None
    ) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query=query,
                response=None,
                variables=variables,
                globals=globals,
            ),
            team=self.team,
        )

    def _program(self, query: str, globals: Optional[dict] = None) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata", language=HogLanguage.HOG, query=query, globals=globals, response=None
            ),
            team=self.team,
        )

    def _template(self, query: str) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(kind="HogQLMetadata", language=HogLanguage.HOG_TEMPLATE, query=query, response=None),
            team=self.team,
        )

    def test_metadata_valid_expr_select(self):
        metadata = self._expr("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "select 1",
                "errors": [
                    {
                        "message": "trailing tokens after expression: '1' (Number)",
                        "start": 7,
                        "end": 8,
                        "fix": None,
                    }
                ],
            },
        )

        metadata = self._select("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "select 1",
                "errors": [],
            },
        )

        metadata = self._expr("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "timestamp",
                "errors": [],
            },
        )

        metadata = self._select("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "timestamp",
                "errors": [
                    {
                        "message": "mismatched input 'timestamp' expecting {SELECT, WITH, '{', '(', '<'}",
                        "start": 0,
                        "end": 9,
                        "fix": None,
                    }
                ],
            },
        )

    def test_metadata_expr_parse_error(self):
        metadata = self._expr("1 as true")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "1 as true",
                "errors": [
                    {
                        "message": '"true" cannot be an alias or identifier, as it\'s a reserved keyword',
                        "start": 0,
                        "end": 9,
                        "fix": None,
                    }
                ],
            },
        )

    def test_metadata_expr_resolve_error(self):
        metadata = self._expr("1 + no_field")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "1 + no_field",
                "errors": [
                    {
                        "message": "Unable to resolve field: no_field",
                        "start": 4,
                        "end": 12,
                        "fix": None,
                    }
                ],
            },
        )

    def test_metadata_warns_for_unknown_event_literal(self):
        EventDefinition.objects.create(team=self.team, name="paid_bill")

        metadata = self._select("SELECT count() FROM events WHERE event = 'purchase'")

        self.assertTrue(metadata.isValid)
        self.assertEqual(len(metadata.errors), 0)
        self.assertEqual(len(metadata.warnings), 1)
        self.assertEqual(
            metadata.warnings[0].message,
            "Event 'purchase' was not found in this project taxonomy.",
        )
        self.assertIsNone(metadata.warnings[0].fix)

    def test_metadata_suggests_similar_event_literal(self):
        EventDefinition.objects.create(team=self.team, name="$pageview")

        metadata = self._select("SELECT count() FROM events WHERE event = 'pageview'")

        self.assertTrue(metadata.isValid)
        self.assertEqual(len(metadata.warnings), 1)
        self.assertEqual(
            metadata.warnings[0].message,
            "Event 'pageview' was not found in this project taxonomy. Did you mean '$pageview'?",
        )
        self.assertEqual(metadata.warnings[0].fix, "'$pageview'")

    def test_metadata_does_not_warn_for_known_event_literal(self):
        EventDefinition.objects.create(team=self.team, name="paid_bill")

        metadata = self._select("SELECT count() FROM events WHERE event = 'paid_bill'")

        self.assertTrue(metadata.isValid)
        self.assertEqual(metadata.warnings, [])

    def test_metadata_warns_for_unknown_event_in_literal(self):
        EventDefinition.objects.create(team=self.team, name="signed_up")

        metadata = self._select("SELECT count() FROM events WHERE event IN ('signed_up', 'signup')")

        self.assertTrue(metadata.isValid)
        warning_messages = [warning.message for warning in metadata.warnings]
        self.assertIn(
            "Event 'signup' was not found in this project taxonomy. Did you mean 'signed_up'?", warning_messages
        )
        self.assertNotIn("Event 'signed_up' was not found in this project taxonomy.", warning_messages)

    def test_metadata_warns_for_unknown_property_field_access(self):
        PropertyDefinition.objects.create(team=self.team, name="$geoip_country_code")

        metadata = self._select("SELECT properties.country_code, count() FROM events GROUP BY properties.country_code")

        self.assertTrue(metadata.isValid)
        self.assertEqual(len(metadata.errors), 0)
        self.assertEqual(len(metadata.warnings), 1)
        self.assertEqual(
            metadata.warnings[0].message,
            "Property 'country_code' was not found in this project taxonomy. Did you mean '$geoip_country_code'?",
        )
        self.assertEqual(metadata.warnings[0].fix, "properties.$geoip_country_code")

    def test_metadata_warns_for_unknown_property_array_access(self):
        PropertyDefinition.objects.create(team=self.team, name="$geoip_country_code")

        metadata = self._select("SELECT properties['country_code'] FROM events")

        self.assertTrue(metadata.isValid)
        self.assertEqual(len(metadata.errors), 0)
        self.assertEqual(len(metadata.warnings), 1)
        self.assertEqual(metadata.warnings[0].fix, "'$geoip_country_code'")

    def test_metadata_does_not_warn_for_known_property_access(self):
        PropertyDefinition.objects.create(team=self.team, name="country_code")

        metadata = self._select("SELECT properties.country_code FROM events")

        self.assertTrue(metadata.isValid)
        self.assertEqual(metadata.warnings, [])

    def test_metadata_does_not_warn_for_dynamic_event_expression(self):
        EventDefinition.objects.create(team=self.team, name="paid_bill")

        metadata = self._select("SELECT count() FROM events WHERE event = concat('paid_', 'bill')")

        taxonomy_warnings = [warning for warning in metadata.warnings if "project taxonomy" in warning.message]
        self.assertEqual(taxonomy_warnings, [])

    def test_metadata_does_not_warn_for_dynamic_property_access(self):
        metadata = self._select("SELECT properties[key] FROM events")

        taxonomy_warnings = [warning for warning in metadata.warnings if "project taxonomy" in warning.message]
        self.assertEqual(taxonomy_warnings, [])

    def test_metadata_does_not_warn_for_allowlisted_dynamic_property(self):
        PropertyDefinition.objects.create(team=self.team, name="$geoip_country_code")

        metadata = self._select("SELECT properties['$feature/my-flag'] FROM events")

        taxonomy_warnings = [warning for warning in metadata.warnings if "project taxonomy" in warning.message]
        self.assertEqual(taxonomy_warnings, [])

    @parameterized.expand(
        [
            (event, prop)
            for event in ("$pageview", "$exception")
            for prop in (
                "$virt_traffic_type",
                "$virt_traffic_category",
                "$virt_bot_name",
                "$virt_bot_operator",
                "$virt_is_bot",
            )
        ]
    )
    def test_metadata_does_not_warn_for_virtual_property(self, event: str, prop: str):
        # Virtual properties are computed at query time and never stored as PropertyDefinition rows, so
        # they must not be flagged as unknown even though read_taxonomy lists them.
        EventDefinition.objects.create(team=self.team, name=event)

        metadata = self._select(f"SELECT properties.{prop} FROM events WHERE event = '{event}'")

        taxonomy_warnings = [warning for warning in metadata.warnings if "project taxonomy" in warning.message]
        self.assertEqual(taxonomy_warnings, [])

    def test_metadata_skips_full_taxonomy_fetch_for_known_event(self):
        EventDefinition.objects.create(team=self.team, name="paid_bill")

        with patch("posthog.hogql.taxonomy_validation._known_names") as known_names:
            metadata = self._select("SELECT count() FROM events WHERE event = 'paid_bill'")

        self.assertTrue(metadata.isValid)
        known_names.assert_not_called()

    def test_metadata_event_literal_fix_preserves_quotes(self):
        EventDefinition.objects.create(team=self.team, name="$pageview")

        query = "SELECT count() FROM events WHERE event = 'pagevisit'"
        warning = self._select(query).warnings[0]

        # Apply the fix exactly as the editor quick-fix does: replace [start, end] with fix.
        replaced = query[: warning.start] + (warning.fix or "") + query[warning.end :]
        self.assertEqual(replaced, "SELECT count() FROM events WHERE event = '$pageview'")

    def test_metadata_property_field_fix_preserves_prefix(self):
        PropertyDefinition.objects.create(team=self.team, name="$geoip_country_code")

        query = "SELECT properties.country_code FROM events"
        warning = self._select(query).warnings[0]

        replaced = query[: warning.start] + (warning.fix or "") + query[warning.end :]
        self.assertEqual(replaced, "SELECT properties.$geoip_country_code FROM events")

    def test_metadata_event_literal_fix_escapes_quote_in_suggestion(self):
        EventDefinition.objects.create(team=self.team, name="o'brien")

        query = "SELECT count() FROM events WHERE event = 'obrien'"
        warning = self._select(query).warnings[0]

        # A suggested name containing a quote must be escaped so the quick-fix stays valid HogQL.
        replaced = query[: warning.start] + (warning.fix or "") + query[warning.end :]
        self.assertEqual(replaced, "SELECT count() FROM events WHERE event = 'o\\'brien'")
        parse_select(replaced)  # round-trips to a parseable query

    def test_metadata_property_field_fix_quotes_suggestion_needing_backticks(self):
        PropertyDefinition.objects.create(team=self.team, name="my prop")

        query = "SELECT properties.myprop FROM events"
        warning = self._select(query).warnings[0]

        replaced = query[: warning.start] + (warning.fix or "") + query[warning.end :]
        self.assertEqual(replaced, "SELECT properties.`my prop` FROM events")
        parse_select(replaced)

    def test_metadata_taxonomy_db_error_fails_open(self):
        EventDefinition.objects.create(team=self.team, name="paid_bill")

        with patch(
            "posthog.hogql.taxonomy_validation.EventDefinition.objects.filter",
            side_effect=DatabaseError("boom"),
        ):
            metadata = self._select("SELECT count() FROM events WHERE event = 'purchase'")

        # A DB error during the advisory taxonomy lookup must not invalidate a valid query.
        self.assertTrue(metadata.isValid)
        self.assertEqual([w for w in metadata.warnings if "project taxonomy" in w.message], [])

    def test_metadata_does_not_query_taxonomy_without_taxonomy_references(self):
        with (
            patch("posthog.hogql.taxonomy_validation.EventDefinition.objects.filter") as event_filter,
            patch("posthog.hogql.taxonomy_validation.PropertyDefinition.objects.filter") as property_filter,
        ):
            metadata = self._select("SELECT count() FROM events")

        self.assertTrue(metadata.isValid)
        event_filter.assert_not_called()
        property_filter.assert_not_called()

    def test_metadata_does_not_warn_for_event_column_outside_events_table(self):
        EventDefinition.objects.create(team=self.team, name="paid_bill")

        metadata = self._select("SELECT count() FROM (SELECT 'signup' AS event) WHERE event = 'signup'")

        taxonomy_warnings = [warning for warning in metadata.warnings if "project taxonomy" in warning.message]
        self.assertEqual(taxonomy_warnings, [])

    def test_metadata_table(self):
        metadata = self._expr("timestamp", "events")
        self.assertEqual(metadata.isValid, True)

        metadata = self._expr("timestamp", "persons")
        self.assertEqual(metadata.isValid, False)

        metadata = self._expr("is_identified", "events")
        self.assertEqual(metadata.isValid, False)

        metadata = self._expr("is_identified", "persons")
        self.assertEqual(metadata.isValid, True)

    @patch("posthog.hogql.metadata.Database.create_for")
    def test_metadata_resolves_database_from_connection_id(self, mock_create_for):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="SELECT 1",
                response=None,
                connectionId=str(source.id),
            ),
            team=self.team,
            user=self.user,
        )

        self.assertEqual(mock_create_for.call_count, 1)
        self.assertEqual(mock_create_for.call_args.kwargs["team"], self.team)
        self.assertEqual(mock_create_for.call_args.kwargs["user"], self.user)
        self.assertEqual(mock_create_for.call_args.kwargs["connection_id"], str(source.id))
        self.assertIn("modifiers", mock_create_for.call_args.kwargs)

    def test_metadata_rejects_soft_deleted_connection_id(self):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            deleted=True,
        )

        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="SELECT 1",
                response=None,
                connectionId=str(source.id),
            ),
            team=self.team,
        )

        self.assertFalse(metadata.isValid)
        self.assertEqual([error.message for error in metadata.errors], [INVALID_CONNECTION_ID_ERROR])

    def test_metadata_with_direct_connection_does_not_allow_posthog_tables(self):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="posthog_user",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="SELECT * FROM persons LIMIT 1",
                response=None,
                connectionId=str(source.id),
            ),
            team=self.team,
        )

        self.assertFalse(metadata.isValid)
        self.assertTrue(any("persons" in (error.message or "") for error in metadata.errors))

    def test_metadata_with_direct_connection_allows_canonical_direct_table_names(self):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        table = DataWarehouseTable.objects.create(
            name="posthog_user",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        ExternalDataSchema.objects.create(
            name="posthog_user",
            team=self.team,
            source=source,
            table=table,
        )

        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="SELECT * FROM posthog_user LIMIT 1",
                response=None,
                connectionId=str(source.id),
            ),
            team=self.team,
        )

        self.assertTrue(metadata.isValid)
        self.assertEqual(metadata.errors, [])

    def test_metadata_with_direct_connection_allows_connection_metadata_function_in_expr(self):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
            connection_metadata={"available_functions": ["icu_collate_nl"]},
        )
        table = DataWarehouseTable.objects.create(
            name="posthog_user",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"name": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}},
        )
        ExternalDataSchema.objects.create(
            name="posthog_user",
            team=self.team,
            source=source,
            table=table,
        )

        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL_EXPR,
                query="icu_collate_nl(name, 'nl')",
                sourceQuery=HogQLQuery(query="select * from posthog_user"),
                response=None,
                connectionId=str(source.id),
            ),
            team=self.team,
        )

        self.assertTrue(metadata.isValid)
        self.assertEqual(metadata.errors, [])

    def test_metadata_with_direct_connection_does_not_allow_disabled_tables(self):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        table = DataWarehouseTable.objects.create(
            name="posthog_user",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        ExternalDataSchema.objects.create(
            name="posthog_user",
            team=self.team,
            source=source,
            table=table,
            should_sync=False,
        )

        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="SELECT * FROM posthog_user LIMIT 1",
                response=None,
                connectionId=str(source.id),
            ),
            team=self.team,
        )

        self.assertFalse(metadata.isValid)
        self.assertTrue(any("posthog_user" in (error.message or "") for error in metadata.errors))

    def test_metadata_rejects_non_direct_connection_id(self):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            prefix="stripe",
        )
        metadata = get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="SELECT 1",
                response=None,
                connectionId=str(selected_source.id),
            ),
            team=self.team,
        )

        self.assertFalse(metadata.isValid)
        self.assertEqual([error.message for error in metadata.errors], [INVALID_CONNECTION_ID_ERROR])

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_metadata_in_cohort(self):
        cohort = Cohort.objects.create(team=self.team, name="cohort_name")
        query = (
            f"select person_id from events where person_id in cohort {cohort.pk} or person_id in cohort '{cohort.name}'"
        )
        metadata = self._select(query)
        self.assertEqual(
            metadata.model_dump(),
            metadata.model_dump()
            | {
                "isValid": True,
                "query": query,
                "notices": [
                    {
                        "message": "Field 'person_id' is of type 'String'",
                        "start": 7,
                        "end": 16,
                        "fix": None,
                    },
                    {
                        "message": f"Cohort #{cohort.pk} can also be specified as '{cohort.name}'",
                        "start": 55,
                        "end": 55 + len(str(cohort.pk)),
                        "fix": f"'{cohort.name}'",
                    },
                    {
                        "message": "Field 'person_id' is of type 'String'",
                        "start": 35,
                        "end": 44,
                        "fix": None,
                    },
                    {
                        "message": f"Searching for cohort by name. Replace with numeric ID {cohort.pk} to protect against renaming.",
                        "start": 79 + len(str(cohort.pk)),
                        "end": 92 + len(str(cohort.pk)),
                        "fix": str(cohort.pk),
                    },
                    {
                        "message": "Field 'person_id' is of type 'String'",
                        "start": 59 + len(str(cohort.pk)),
                        "end": 68 + len(str(cohort.pk)),
                        "fix": None,
                    },
                ],
            },
        )

    def test_metadata_property_type_notice_debug(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "number")

        PropertyDefinition.objects.create(team=self.team, name="string", property_type="String")
        PropertyDefinition.objects.create(team=self.team, name="number", property_type="Numeric")
        metadata = self._expr("properties.string || properties.number")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "properties.string || properties.number",
                "notices": [
                    {
                        "message": "Event property 'string' is of type 'String'. This property is not materialized 🐢.",
                        "start": 11,
                        "end": 17,
                        "fix": None,
                    },
                    {
                        "message": "Event property 'number' is of type 'Float'. This property is materialized (mat_*) ⚡️.",
                        "start": 32,
                        "end": 38,
                        "fix": None,
                    },
                ],
            },
        )

    def test_metadata_replaces_variable_placeholders(self):
        insight_variable = InsightVariable.objects.create(
            team=self.team,
            name="Company",
            code_name="company_name",
            type=InsightVariable.Type.STRING,
        )
        metadata = self._select_with_variables(
            "SELECT {variables.company_name}",
            variables={
                "company_name": {
                    "code_name": "company_name",
                    "value": "Acme",
                    "variableId": str(insight_variable.id),
                }
            },
        )

        self.assertTrue(metadata.isValid)
        self.assertEqual(metadata.errors, [])

    def test_metadata_variable_placeholder_without_variables(self):
        metadata = self._select_with_variables("SELECT {variables.company_name}")

        self.assertFalse(metadata.isValid)
        self.assertEqual(len(metadata.errors), 1)
        self.assertIn("company_name", metadata.errors[0].message)

    def test_metadata_property_type_notice_no_debug(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "number")

        PropertyDefinition.objects.create(team=self.team, name="string", property_type="String")
        PropertyDefinition.objects.create(team=self.team, name="number", property_type="Numeric")
        metadata = self._expr("properties.string || properties.number", debug=False)
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "properties.string || properties.number",
                "notices": [
                    {
                        "message": "Event property 'string' is of type 'String'.",
                        "start": 11,
                        "end": 17,
                        "fix": None,
                    },
                    {
                        "message": "Event property 'number' is of type 'Float'.",
                        "start": 32,
                        "end": 38,
                        "fix": None,
                    },
                ],
            },
        )

    def test_valid_view(self):
        metadata = self._select("select event AS event FROM events")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "select event AS event FROM events",
                "errors": [],
            },
        )

    def test_valid_view_nested_view(self):
        saved_query_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event as event from events LIMIT 100",
                },
            },
        )

        metadata = self._select("select event AS event FROM event_view")

        self.assertEqual(saved_query_response.status_code, 201, saved_query_response.json())
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "select event AS event FROM event_view",
                "errors": [],
            },
        )

    def test_union_all_does_not_crash(self):
        metadata = self._select("SELECT events.event FROM events UNION ALL SELECT events.event FROM events WHERE 1 = 2")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "errors": [],
            },
        )

    def test_hog_program(self):
        metadata = self._program("let i := 3")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "errors": [],
            },
        )

    def test_hog_program_invalid(self):
        metadata = self._program("let i := NONO()")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "query": "let i := NONO()",
                "isValid": False,
                "notices": [],
                "warnings": [],
                "errors": [{"end": 15, "fix": None, "message": "Hog function `NONO` is not implemented", "start": 9}],
            },
        )

    def test_hog_program_globals(self):
        metadata = self._program("print(event, region)", globals={"event": "banana"})
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "query": "print(event, region)",
                "isValid": True,
                "notices": [{"end": 11, "fix": None, "message": "Global variable: event", "start": 6}],
                "warnings": [{"end": 19, "fix": None, "message": "Unknown global variable: region", "start": 13}],
                "errors": [],
            },
        )

    def test_string_template(self):
        metadata = self._program("this is a {event} string")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "errors": [],
            },
        )

    def test_string_template_invalid(self):
        metadata = self._program("this is a {NONO()} string")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "errors": [{"end": 17, "fix": None, "message": "Hog function `NONO` is not implemented", "start": 11}],
            },
        )

    def test_is_valid_view_when_all_fields_have_aliases(self):
        metadata = self._select("SELECT event AS event FROM events")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "SELECT event AS event FROM events",
                "errors": [],
            },
        )

    def test_is_valid_view_is_true_when_not_all_fields_have_aliases(self):
        metadata = self._select("SELECT event AS event, uuid FROM events")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "SELECT event AS event, uuid FROM events",
                "errors": [],
            },
        )

    def test_is_valid_view_is_false_when_fields_that_are_transformations_dont_have_aliases(self):
        metadata = self._select("SELECT toDate(timestamp), count() FROM events GROUP BY toDate(timestamp)")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "SELECT toDate(timestamp), count() FROM events GROUP BY toDate(timestamp)",
                "errors": [],
            },
        )

    def test_is_valid_view_is_true_when_fields_that_are_transformations_have_aliases(self):
        metadata = self._select(
            "SELECT toDate(timestamp) as timestamp, count() as total_count FROM events GROUP BY timestamp"
        )
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "SELECT toDate(timestamp) as timestamp, count() as total_count FROM events GROUP BY timestamp",
                "errors": [],
            },
        )

    def test_is_valid_view_is_false_when_using_asterisk(self):
        metadata = self._select("SELECT * FROM events")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "SELECT * FROM events",
                "errors": [],
            },
        )

    def test_is_valid_view_is_false_when_using_scoped_asterisk(self):
        metadata = self._select("SELECT e.* FROM events e")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "SELECT e.* FROM events e",
                "errors": [],
            },
        )

    def test_table_collector_basic_select(self):
        metadata = self._select("SELECT event FROM events")
        self.assertEqual(metadata.table_names, ["events"])

    def test_table_collector_multiple_tables(self):
        metadata = self._select(
            "SELECT events.event, persons.properties.name FROM events JOIN persons ON events.person_id = persons.id"
        )
        self.assertEqual(metadata.isValid, True)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["events", "persons"]))

    def test_table_collector_with_cte(self):
        metadata = self._select("""
            WITH events_count AS (
                SELECT count(*) as count FROM events
            )
            SELECT * FROM events_count
        """)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["events"]))

    def test_table_collector_subquery(self):
        metadata = self._select("""
            SELECT * FROM (
                SELECT person_id FROM events
                UNION ALL
                SELECT id FROM persons
            )
        """)
        self.assertEqual(metadata.isValid, True)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["events", "persons"]))

    def test_table_in_filter(self):
        metadata = self._select("SELECT * FROM events WHERE events.person_id IN (SELECT id FROM persons)")
        self.assertEqual(metadata.isValid, True)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["events", "persons"]))

    def test_table_collector_complex_query(self):
        metadata = self._select("""
            WITH user_counts AS (
                SELECT person_id, count(*) as count
                FROM events
                GROUP BY person_id
            )
            SELECT
                p.properties.name,
                uc.count
            FROM persons p
            LEFT JOIN user_counts uc ON p.id = uc.person_id
            LEFT JOIN cohort_people c ON p.id = c.person_id
        """)
        self.assertEqual(metadata.isValid, True)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["events", "persons", "cohort_people"]))

    def test_experimental_join_condition(self):
        metadata = self._select("""
        SELECT t1.a
        FROM
            (SELECT number AS a, number * 10 AS b FROM numbers(5)) AS t1
        JOIN
            (SELECT number AS key, number * 2 AS c, number * 3 AS d FROM numbers(5)) AS t2
        ON t1.a = t2.key
        WHERE t1.b > 0 AND t2.c < t2.d
        """)
        self.assertEqual(metadata.isValid, True)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["numbers"]))

    def test_table_collector_lazy_join(self):
        metadata = self._select(
            """
        SELECT events.session.id FROM events
        """,
            modifiers=HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V3),
        )
        self.assertEqual(metadata.isValid, True)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["events"]))
        self.assertEqual(sorted(metadata.ch_table_names or []), sorted(["events", "raw_sessions_v3"]))

    def test_views_type_resolution(self):
        _source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="prefix",
        )

        metadata = self._select("SELECT metadata, metadata.name AS name FROM stripe.prefix.customer_revenue_view")
        self.assertEqual(metadata.isValid, True)
        self.assertEqual(sorted(metadata.table_names or []), sorted(["stripe.prefix.customer_revenue_view"]))

        # Doesn't include `name` because it's a property access and not a field
        # TODO: Should *probably* update the code to resolve that type as well
        self.assertEqual([notice.message for notice in metadata.notices or []], ["Field 'metadata' is of type 'JSON'"])

    def test_metadata_warns_about_similar_subquery_in_singular(self):
        metadata = self._select(
            """
            SELECT *
            FROM (
                SELECT person_id, count() AS total
                FROM events
                GROUP BY person_id
            ) a
            JOIN (
                SELECT person_id, max(timestamp) AS last_seen
                FROM events
                GROUP BY person_id
            ) b ON a.person_id = b.person_id
            """
        )

        self.assertTrue(any("very similar to 1 other subquery" in warning.message for warning in metadata.warnings))
        self.assertTrue(all(warning.fix is None for warning in metadata.warnings))

    def test_metadata_warns_about_similar_subquery_in_plural(self):
        metadata = self._select(
            """
            SELECT *
            FROM (
                SELECT person_id, count() AS total
                FROM events
                GROUP BY person_id
            ) a
            JOIN (
                SELECT person_id, max(timestamp) AS last_seen
                FROM events
                GROUP BY person_id
            ) b ON a.person_id = b.person_id
            JOIN (
                SELECT person_id, min(timestamp) AS first_seen
                FROM events
                GROUP BY person_id
            ) c ON a.person_id = c.person_id
            """
        )

        self.assertTrue(any("very similar to 2 other subqueries" in warning.message for warning in metadata.warnings))
        self.assertTrue(all(warning.fix is None for warning in metadata.warnings))

    def test_metadata_does_not_warn_for_distinct_subquery_sources(self):
        metadata = self._select(
            """
            SELECT *
            FROM (
                SELECT person_id, count() AS total
                FROM events
                GROUP BY person_id
            ) a
            JOIN (
                SELECT id, created_at
                FROM persons
            ) b ON a.person_id = b.id
            """
        )

        self.assertFalse(any("very similar" in warning.message for warning in metadata.warnings))
