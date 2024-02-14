from posthog.hogql.autocomplete import get_hogql_autocomplete
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.persons import PERSONS_FIELDS
from posthog.models.property_definition import PropertyDefinition
from posthog.schema import HogQLAutocomplete, HogQLAutocompleteResponse
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


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

    def _query_response(self, query: str, start: int, end: int) -> HogQLAutocompleteResponse:
        autocomplete = HogQLAutocomplete(kind="HogQLAutocomplete", select=query, startPosition=start, endPosition=end)
        return get_hogql_autocomplete(query=autocomplete, team=self.team)

    def test_autocomplete(self):
        query = "select * from events"
        results = self._query_response(query=query, start=0, end=0)
        assert len(results.suggestions) == 0

    def test_autocomplete_events_suggestions(self):
        query = "select  from events"
        results = self._query_response(query=query, start=7, end=7)
        assert len(results.suggestions) != 0

    def test_autocomplete_functions(self):
        query = "select  from events"
        results = self._query_response(query=query, start=7, end=7)
        assert "toDateTime" in [suggestion.label for suggestion in results.suggestions]
        assert "toDateTime()" in [suggestion.insertText for suggestion in results.suggestions]

    def test_autocomplete_persons_suggestions(self):
        query = "select  from persons"
        results = self._query_response(query=query, start=7, end=7)
        assert len(results.suggestions) != 0

    def test_autocomplete_assume_events_table(self):
        query = "select "
        results = self._query_response(query=query, start=7, end=7)
        assert len(results.suggestions) != 0
        assert "event" in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_events_properties(self):
        self._create_properties()

        query = "select properties. from events"
        results = self._query_response(query=query, start=18, end=18)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_event_value"

    def test_autocomplete_persons_properties(self):
        self._create_properties()

        query = "select properties. from persons"
        results = self._query_response(query=query, start=18, end=18)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_person_value"

    def test_autocomplete_lazy_join(self):
        query = "select pdi. from events"
        results = self._query_response(query=query, start=11, end=11)
        assert len(results.suggestions) == 4

    def test_autocomplete_virtual_table(self):
        query = "select poe. from events"
        results = self._query_response(query=query, start=11, end=11)
        assert len(results.suggestions) != 0

    def test_autocomplete_events_properties_partial_matching(self):
        self._create_properties()

        query = "select properties.some_ from events"
        results = self._query_response(query=query, start=18, end=23)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_event_value"

    def test_autocomplete_nested_tables(self):
        # Inner table
        query = "select event, (select  from persons) as blah from events"
        results = self._query_response(query=query, start=22, end=22)

        keys = list(PERSONS_FIELDS.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

        # Outer table
        query = "select , (select id from persons) as blah from events"
        results = self._query_response(query=query, start=7, end=7)

        keys = list(EventsTable().fields.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

    def test_autocomplete_table_name(self):
        query = "select event from "
        results = self._query_response(query=query, start=18, end=18)
        assert len(results.suggestions) != 0

    def test_autocomplete_table_name_dot_notation(self):
        query = "select event from events."
        results = self._query_response(query=query, start=25, end=25)
        assert len(results.suggestions) == 0

    def test_autocomplete_recursive_fields(self):
        self._create_properties()

        query = "select pdi.person.properties. from events"
        results = self._query_response(query=query, start=29, end=29)
        assert len(results.suggestions) == 1
        assert results.suggestions[0].label == "some_person_value"

    def test_autocomplete_subquery_cte(self):
        query = "select e from (select event from events)"
        results = self._query_response(query=query, start=7, end=8)
        assert results.suggestions[0].label == "event"
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_with_cte(self):
        query = "with blah as (select event from events) select e from blah"
        results = self._query_response(query=query, start=47, end=48)
        assert results.suggestions[0].label == "event"
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_cte_alias(self):
        query = "select p from (select event as potato from events)"
        results = self._query_response(query=query, start=7, end=8)
        assert results.suggestions[0].label == "potato"
        assert "event" not in [suggestion.label for suggestion in results.suggestions]
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_cte_constant_type(self):
        query = "select p from (select 'hello' as potato from events)"
        results = self._query_response(query=query, start=7, end=8)
        assert results.suggestions[0].label == "potato"
        assert "event" not in [suggestion.label for suggestion in results.suggestions]
        assert "properties" not in [suggestion.label for suggestion in results.suggestions]

    def test_autocomplete_field_traversers(self):
        query = "select person. from events"
        results = self._query_response(query=query, start=14, end=14)
        assert len(results.suggestions) != 0

    def test_autocomplete_table_alias(self):
        query = "select  from events e"
        results = self._query_response(query=query, start=7, end=7)
        assert len(results.suggestions) != 0
        assert results.suggestions[0].label == "e"

    def test_autocomplete_complete_list(self):
        query = "select event from events"
        results = self._query_response(query=query, start=7, end=12)
        assert results.incomplete_list is False

    def test_autocomplete_incomplete_list(self):
        query = "select properties. from events"
        results = self._query_response(query=query, start=18, end=18)
        assert results.incomplete_list is True

    def test_autocomplete_joined_tables(self):
        query = "select p. from events e left join persons p on e.person_id = p.id"
        results = self._query_response(query=query, start=9, end=9)

        assert len(results.suggestions) != 0

        keys = list(PERSONS_FIELDS.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

    def test_autocomplete_joined_table_contraints(self):
        query = "select p.id from events e left join persons p on e.person_id = p."
        results = self._query_response(query=query, start=65, end=65)

        assert len(results.suggestions) != 0

        keys = list(PERSONS_FIELDS.keys())

        for index, key in enumerate(keys):
            assert results.suggestions[index].label == key

    def test_autocomplete_joined_tables_aliases(self):
        query = "select  from events e left join persons p on e.person_id = p.id"
        results = self._query_response(query=query, start=7, end=7)

        assert len(results.suggestions) == 2
        assert results.suggestions[0].label == "e"
        assert results.suggestions[1].label == "p"
