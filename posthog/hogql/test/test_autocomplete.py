from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import (
    AutocompleteCompletionItemKind,
    HogLanguage,
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
    HogQLQuery,
)

from posthog.hogql import ast
from posthog.hogql.autocomplete import get_hogql_autocomplete
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import StringDatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.persons import PERSONS_FIELDS

from posthog.models.insight_variable import InsightVariable
from posthog.models.property_definition import PropertyDefinition
from posthog.warehouse.models import ExternalDataSource
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.types import ExternalDataSourceType


class TestAutocomplete(ClickhouseTestMixin, APIBaseTest):
    def _create_properties(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="some_event_value",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="some_person_value",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )

    def _select(
        self, query: str, start: int, end: int, database: Optional[Database] = None
    ) -> HogQLAutocompleteResponse:
        autocomplete = HogQLAutocomplete(
            kind="HogQLAutocomplete", query=query, language=HogLanguage.HOG_QL, startPosition=start, endPosition=end
        )
        return get_hogql_autocomplete(query=autocomplete, team=self.team, database_arg=database)

    def _expr(self, query: str, start: int, end: int, database: Optional[Database] = None) -> HogQLAutocompleteResponse:
        autocomplete = HogQLAutocomplete(
            kind="HogQLAutocomplete",
            query=query,
            language=HogLanguage.HOG_QL_EXPR,
            sourceQuery=HogQLQuery(query="select * from events"),
            startPosition=start,
            endPosition=end,
        )
        return get_hogql_autocomplete(query=autocomplete, team=self.team, database_arg=database)

    def _template(
        self, query: str, start: int, end: int, database: Optional[Database] = None
    ) -> HogQLAutocompleteResponse:
        autocomplete = HogQLAutocomplete(
            kind="HogQLAutocomplete",
            query=query,
            language=HogLanguage.HOG_TEMPLATE,
            globals={"event": "$pageview"},
            startPosition=start,
            endPosition=end,
        )
        return get_hogql_autocomplete(query=autocomplete, team=self.team, database_arg=database)

    def _json(self, query: str, start: int, end: int, database: Optional[Database] = None) -> HogQLAutocompleteResponse:
        autocomplete = HogQLAutocomplete(
            kind="HogQLAutocomplete",
            query=query,
            language=HogLanguage.HOG_JSON,
            globals={"event": "$pageview"},
            startPosition=start,
            endPosition=end,
        )
        return get_hogql_autocomplete(query=autocomplete, team=self.team, database_arg=database)

    def _program(
        self, query: str, start: int, end: int, database: Optional[Database] = None
    ) -> HogQLAutocompleteResponse:
        autocomplete = HogQLAutocomplete(
            kind="HogQLAutocomplete",
            query=query,
            language=HogLanguage.HOG,
            globals={"event": "$pageview"},
            startPosition=start,
            endPosition=end,
        )
        return get_hogql_autocomplete(query=autocomplete, team=self.team, database_arg=database)

    def test_autocomplete(self):
        query = "select * from events"
        results = self._select(query=query, start=0, end=0)
        assert len(results.suggestions) == 0

    def test_autocomplete_events_suggestions(self):
        query = "select  from events"
        results = self._select(query=query, start=7, end=7)
        assert len(results.suggestions) != 0

    def test_autocomplete_functions(self):
        query = "select  from events"
        results = self._select(query=query, start=7, end=7)
        assert "toDateTime" in [suggestion.label for suggestion in results.suggestions]
        assert "toDateTime()" in [suggestion.insertText for suggestion in results.suggestions]

    def test_autocomplete_persons_suggestions(self):
        query = "select  from persons"
        results = self._select(query=query, start=7, end=7)
        assert len(results.suggestions) != 0

    def test_autocomplete_assume_events_table(self):
        query = "select "
        results = self._select(query=query, start=7, end=7)
        assert len(results.suggestions) != 0
        assert "event" in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_events_properties(self):
        self._create_properties()

        query = "select properties. from events"
        results = self._select(query=query, start=18, end=18)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_event_value"

    def test_autocomplete_persons_properties(self):
        self._create_properties()

        query = "select properties. from persons"
        results = self._select(query=query, start=18, end=18)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_person_value"

    def test_autocomplete_lazy_join(self):
        query = "select pdi. from events"
        results = self._select(query=query, start=11, end=11)
        assert len(results.suggestions) == 4

    def test_autocomplete_virtual_table(self):
        query = "select poe. from events"
        results = self._select(query=query, start=11, end=11)
        assert len(results.suggestions) != 0

    def test_autocomplete_events_properties_partial_matching(self):
        self._create_properties()

        query = "select properties.some_ from events"
        results = self._select(query=query, start=18, end=23)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_event_value"

    def test_autocomplete_nested_tables(self):
        # Inner table
        query = "select event, (select  from persons) as blah from events"
        results = self._select(query=query, start=22, end=22)

        keys = list(PERSONS_FIELDS.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

        # Outer table
        query = "select , (select id from persons) as blah from events"
        results = self._select(query=query, start=7, end=7)

        keys = list(EventsTable().fields.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

    def test_autocomplete_table_name(self):
        query = "select event from "
        results = self._select(query=query, start=18, end=18)
        assert len(results.suggestions) != 0

    def test_autocomplete_table_name_dot_notation(self):
        query = "select event from events."
        results = self._select(query=query, start=25, end=25)
        assert len(results.suggestions) == 0

    def test_autocomplete_recursive_fields(self):
        self._create_properties()

        query = "select pdi.person.properties. from events"
        results = self._select(query=query, start=29, end=29)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_person_value"

    def test_autocomplete_subquery_cte(self):
        query = "select e from (select event from events)"
        results = self._select(query=query, start=7, end=8)
        assert results.suggestions[0].label == "event"
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_with_cte(self):
        query = "with blah as (select event from events) select e from blah"
        results = self._select(query=query, start=47, end=48)
        assert results.suggestions[0].label == "event"
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_cte_alias(self):
        query = "select p from (select event as potato from events)"
        results = self._select(query=query, start=7, end=8)
        assert results.suggestions[0].label == "potato"
        assert "event" not in [suggestion.label for suggestion in results.suggestions]
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_cte_constant_type(self):
        query = "select p from (select 'hello' as potato from events)"
        results = self._select(query=query, start=7, end=8)
        assert results.suggestions[0].label == "potato"
        assert "event" not in [suggestion.label for suggestion in results.suggestions]
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_field_traversers(self):
        query = "select person. from events"
        results = self._select(query=query, start=14, end=14)
        assert len(results.suggestions) != 0

    def test_autocomplete_table_alias(self):
        query = "select  from events e"
        results = self._select(query=query, start=7, end=7)
        assert len(results.suggestions) != 0
        assert results.suggestions[0].label == "e"

    def test_autocomplete_complete_list(self):
        query = "select event from events"
        results = self._select(query=query, start=7, end=12)
        assert results.incomplete_list is False

    def test_autocomplete_properties_list_with_under_220_properties(self):
        for index in range(20):
            PropertyDefinition.objects.create(
                team=self.team,
                name=f"some_event_value_{index}",
                property_type="String",
                type=PropertyDefinition.Type.EVENT,
            )

        query = "select properties. from events"
        results = self._select(query=query, start=18, end=18)
        assert results.incomplete_list is False

    def test_autocomplete_properties_list_with_over_220_properties(self):
        for index in range(221):
            PropertyDefinition.objects.create(
                team=self.team,
                name=f"some_event_value_{index}",
                property_type="String",
                type=PropertyDefinition.Type.EVENT,
            )

        query = "select properties. from events"
        results = self._select(query=query, start=18, end=18)
        assert results.incomplete_list is True

    def test_autocomplete_joined_tables(self):
        query = "select p. from events e left join persons p on e.person_id = p.id"
        results = self._select(query=query, start=9, end=9)

        assert len(results.suggestions) != 0

        keys = list(PERSONS_FIELDS.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

    def test_autocomplete_joined_table_contraints(self):
        query = "select p.id from events e left join persons p on e.person_id = p."
        results = self._select(query=query, start=65, end=65)

        assert len(results.suggestions) != 0

        keys = list(PERSONS_FIELDS.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

    def test_autocomplete_joined_tables_aliases(self):
        query = "select  from events e left join persons p on e.person_id = p.id"
        results = self._select(query=query, start=7, end=7)

        assert len(results.suggestions) == 2
        assert results.suggestions[0].label == "e"
        assert results.suggestions[1].label == "p"

    def test_autocomplete_non_existing_alias(self):
        query = "select o. from events e"
        results = self._select(query=query, start=9, end=9)

        assert len(results.suggestions) == 0

    def test_autocomplete_events_hidden_field(self):
        database = Database.create_for(team=self.team)
        database.get_table("events").fields["event"] = StringDatabaseField(name="event", hidden=True)

        query = "select  from events"
        results = self._select(query=query, start=7, end=7, database=database)

        for suggestion in results.suggestions:
            assert suggestion.label != "event"

    def test_autocomplete_special_characters(self):
        database = Database.create_for(team=self.team)
        database.get_table("events").fields["event-name"] = StringDatabaseField(name="event-name")

        query = "select  from events"
        results = self._select(query=query, start=7, end=7, database=database)

        suggestions = list(filter(lambda x: x.label == "event-name", results.suggestions))
        assert len(suggestions) == 1

        suggestion = suggestions[0]
        assert suggestion is not None
        assert suggestion.label == "event-name"
        assert suggestion.insertText == "`event-name`"

    def test_autocomplete_expressions(self):
        database = Database.create_for(team=self.team)

        query = "person."
        results = self._expr(query=query, start=7, end=7, database=database)

        suggestions = list(filter(lambda x: x.label == "created_at", results.suggestions))
        assert len(suggestions) == 1

        suggestion = suggestions[0]
        assert suggestion is not None
        assert suggestion.label == "created_at"
        assert suggestion.insertText == "created_at"

    def test_autocomplete_resolve_expression_type(self):
        database = Database.create_for(team=self.team)

        database.get_table("events").fields["expr_field"] = ast.ExpressionField(
            name="expr_field",
            isolate_scope=True,
            expr=ast.Call(name="toDateTime", args=[ast.Constant(value="2025-01-01")]),
        )

        query = "select  from events"
        results = self._select(query=query, start=7, end=7, database=database)

        suggestions = list(filter(lambda x: x.label == "expr_field", results.suggestions))
        assert len(suggestions) == 1

        suggestion = suggestions[0]
        assert suggestion is not None
        assert suggestion.label == "expr_field"
        assert suggestion.insertText == "expr_field"
        assert suggestion.detail == "DateTime"

    def test_autocomplete_template_strings(self):
        database = Database.create_for(team=self.team)

        query = "this isn't a string {concat(eve)} <- this is"
        results = self._template(query=query, start=28, end=31, database=database)

        suggestions = list(filter(lambda x: x.label == "event", results.suggestions))
        assert len(suggestions) == 1

        suggestion = suggestions[0]
        assert suggestion is not None
        assert suggestion.label == "event"
        assert suggestion.insertText == "event"

        results = self._template(query=query, start=5, end=5, database=database)
        assert len(results.suggestions) == 0

        results = self._template(query=query, start=5, end=6, database=database)
        assert len(results.suggestions) == 0

    def test_autocomplete_template_json(self):
        database = Database.create_for(team=self.team)

        query = '{ "key": "val_{event.distinct_id}_ue" }'
        results = self._json(query=query, start=15, end=20, database=database)

        suggestions = list(filter(lambda x: x.label == "event", results.suggestions))
        assert len(suggestions) == 1

        suggestion = suggestions[0]
        assert suggestion is not None
        assert suggestion.label == "event"
        assert suggestion.insertText == "event"

        results = self._json(query=query, start=5, end=5, database=database)
        assert len(results.suggestions) == 0

        results = self._json(query=query, start=5, end=6, database=database)
        assert len(results.suggestions) == 0

    def test_autocomplete_hog(self):
        database = Database.create_for(team=self.team)

        # 1
        query = "let var1 := 3; let otherVar := 5; print(v)"
        results = self._program(query=query, start=41, end=41, database=database)

        suggestions = list(filter(lambda x: x.kind == AutocompleteCompletionItemKind.VARIABLE, results.suggestions))
        assert sorted([suggestion.label for suggestion in suggestions]) == ["event", "otherVar", "var1"]

        suggestions = list(filter(lambda x: x.kind == AutocompleteCompletionItemKind.FUNCTION, results.suggestions))
        assert len(suggestions) > 0

        # 2
        query = "let var1 := 3; let otherVar := 5; print(v)"
        results = self._program(query=query, start=16, end=16, database=database)

        suggestions = list(filter(lambda x: x.kind == AutocompleteCompletionItemKind.VARIABLE, results.suggestions))
        assert sorted([suggestion.label for suggestion in suggestions]) == ["event", "var1"]

        # 3
        query = "let var1 := 3; let otherVar := 5; print(v)"
        results = self._program(query=query, start=34, end=34, database=database)

        suggestions = list(filter(lambda x: x.kind == AutocompleteCompletionItemKind.VARIABLE, results.suggestions))
        assert sorted([suggestion.label for suggestion in suggestions]) == ["event", "otherVar", "var1"]

    def test_autocomplete_variables(self):
        InsightVariable.objects.create(team=self.team, name="Variable 1", code_name="variable_1")
        query = "select {}"
        results = self._select(query=query, start=8, end=8)

        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "variables.variable_1"

    def test_autocomplete_variables_partial(self):
        InsightVariable.objects.create(team=self.team, name="Variable 1", code_name="variable_1")
        query = "select {vari}"
        results = self._select(query=query, start=8, end=12)

        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "variables.variable_1"

    def test_autocomplete_variables_prefix(self):
        InsightVariable.objects.create(team=self.team, name="Variable 1", code_name="variable_1")
        query = "select {variables.}"
        results = self._select(query=query, start=8, end=18)

        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "variable_1"

    def test_autocomplete_warehouse_table(self):
        credentials = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        DataWarehouseTable.objects.create(
            team=self.team,
            name="some_table",
            format="CSV",
            url_pattern="http://localhost/file.csv",
            credential=credentials,
        )
        query = "select * from "
        results = self._select(query=query, start=14, end=14)

        assert "some_table" in [x.label for x in results.suggestions]

    def test_autocomplete_warehouse_table_with_source_dot_notation(self):
        credentials = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.STRIPE)
        DataWarehouseTable.objects.create(
            team=self.team,
            name="some_table",
            format="CSV",
            url_pattern="http://localhost/file.csv",
            credential=credentials,
            external_data_source=source,
        )
        query = "select * from "
        results = self._select(query=query, start=14, end=14)

        assert "stripe.some_table" in [x.label for x in results.suggestions]

    def test_autocomplete_warehouse_table_with_source_and_prefix_dot_notation(self):
        credentials = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, prefix="prefix"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="some_table",
            format="CSV",
            url_pattern="http://localhost/file.csv",
            credential=credentials,
            external_data_source=source,
        )
        query = "select * from "
        results = self._select(query=query, start=14, end=14)

        assert "stripe.prefix.some_table" in [x.label for x in results.suggestions]

    def test_autocomplete_warehouse_view(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="some_view",
            query={"query": "select * from events"},
        )
        query = "select * from "
        results = self._select(query=query, start=14, end=14)

        assert "some_view" in [x.label for x in results.suggestions]

    def test_autocomplete_deleted_warehouse_view(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="DELETED",
            query={"query": "select * from events"},
            deleted=True,
            deleted_name="some_view",
        )
        query = "select * from "
        results = self._select(query=query, start=14, end=14)

        assert "some_view" not in [x.label for x in results.suggestions]
        assert "DELETED" not in [x.label for x in results.suggestions]

    def test_autocomplete_empty_source_query(self):
        autocomplete = HogQLAutocomplete(
            kind="HogQLAutocomplete",
            query="SELECT * FROM e",
            language=HogLanguage.HOG_QL,
            sourceQuery=HogQLQuery(query=""),  # Empty source query
            startPosition=15,
            endPosition=15,
        )
        results = get_hogql_autocomplete(query=autocomplete, team=self.team)

        assert "events" in [suggestion.label for suggestion in results.suggestions]
