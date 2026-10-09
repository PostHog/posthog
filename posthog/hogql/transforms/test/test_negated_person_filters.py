import re
from datetime import UTC, datetime, timedelta

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
    materialized,
)
from unittest.mock import patch

from parameterized import param, parameterized

from posthog.schema import HogQLQueryModifiers, MaterializationMode, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.models import PropertyDefinition
from posthog.models.person.util import create_person

from products.event_definitions.backend.models.property_definition import PropertyType

from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

JOINED = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED

INTERNAL = {"key": "email", "type": "person", "operator": "not_icontains", "value": "@internal.example"}
EXAMPLE = {"key": "email", "type": "person", "operator": "not_icontains", "value": "@example.com"}

INTERNAL_PERSONS = {"internal", "changed_to_internal", "merged"}
INTERNAL_OR_EXAMPLE_PERSONS = INTERNAL_PERSONS | {"external", "changed_to_external"}

PERSONS_JOIN = re.compile(r"AS \w+__person ON")

MATERIALIZED_PERSON_COLUMNS = {
    "person": {
        (name, "properties"): MaterializedColumn(
            name=f"pmat_{name}",
            details=MaterializedColumnDetails(table_column="properties", property_name=name, is_disabled=False),
            is_nullable=False,
        )
        for name in ("email", "is_staff")
    }
}


class TestNegatedPersonFiltersResults(ClickhouseTestMixin, APIBaseTest):
    EVENTS = {
        "internal",
        "external",
        "personless",
        "deleted_internal",
        "changed_to_external",
        "changed_to_internal",
        "cleared_email",
        "null_email",
        "no_email",
        "future_internal",
        "merged",
    }

    def setUp(self):
        super().setUp()
        self.enterContext(materialized("person", "email"))
        timestamp = datetime(2024, 1, 2, 12)

        def person(distinct_id: str, properties: dict):
            created = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties=properties)
            _create_event(event=distinct_id, distinct_id=distinct_id, team=self.team, timestamp=timestamp)
            return created

        person("internal", {"email": "alice@internal.example"})
        person("external", {"email": "bob@example.com"})
        _create_event(event="personless", distinct_id="personless", team=self.team, timestamp=timestamp)
        deleted = person("deleted_internal", {"email": "dana@internal.example"})
        to_external = person("changed_to_external", {"email": "erin@internal.example"})
        to_internal = person("changed_to_internal", {"email": "frank@example.com"})
        cleared = person("cleared_email", {"email": "gina@internal.example"})
        person("null_email", {"email": "null"})
        person("no_email", {})
        future = person("future_internal", {"email": "hank@internal.example"})
        person("merged", {"email": "ivy@example.com"})
        flush_persons_and_events()

        in_a_month = datetime.now(UTC) + timedelta(days=30)
        for later, email, is_deleted, created_at in [
            (deleted, "dana@internal.example", True, None),
            (to_external, "erin@example.com", False, None),
            (to_internal, "frank@internal.example", False, None),
            (cleared, "", False, None),
            (future, "hank@internal.example", False, in_a_month),
        ]:
            create_person(
                team_id=self.team.pk,
                uuid=str(later.uuid),
                properties={"email": email},
                version=1,
                is_deleted=is_deleted,
                created_at=created_at,
            )
        create_person_id_override_by_distinct_id("merged", "internal", self.team.pk)

    def _run(self, select: str, filters: list[dict], mode: PersonsOnEventsMode, rewrite: bool) -> tuple[set[str], str]:
        response = execute_hogql_query(
            parse_select(f"{select} WHERE {{where}}"),
            self.team,
            placeholders={"where": property_to_expr(filters, self.team)},
            modifiers=HogQLQueryModifiers(personsOnEventsMode=mode, negatedPersonFiltersNotIn=rewrite),
        )
        assert response.clickhouse is not None
        return {row[0] for row in response.results}, response.clickhouse

    @parameterized.expand(
        [
            param("not_icontains", [INTERNAL], INTERNAL_PERSONS),
            param(
                "not_icontains_multi", [{**INTERNAL, "value": ["@internal.example", "@corp.example"]}], INTERNAL_PERSONS
            ),
            param(
                "not_icontains_past_needle_limit",
                [{**INTERNAL, "value": ["@internal.example", *(f"@unused-{i}.example" for i in range(255))]}],
                INTERNAL_PERSONS,
            ),
            param(
                "is_not",
                [{**INTERNAL, "operator": "is_not", "value": "alice@internal.example"}],
                {"internal", "merged"},
            ),
            param(
                "is_not_multi",
                [{**INTERNAL, "operator": "is_not", "value": ["alice@internal.example", "frank@internal.example"]}],
                INTERNAL_PERSONS,
            ),
            param(
                "not_regex", [{**INTERNAL, "operator": "not_regex", "value": "@internal\\.example$"}], INTERNAL_PERSONS
            ),
            param("two_filters", [INTERNAL, EXAMPLE], INTERNAL_OR_EXAMPLE_PERSONS),
            param(
                "select_alias_named_person_id",
                [INTERNAL],
                INTERNAL_PERSONS,
                select="SELECT event, distinct_id AS person_id FROM events",
            ),
            # DISABLED mode reads person_id through an INNER JOIN on person_distinct_id2. That join drops the
            # personless event and ignores the override.
            param(
                "disabled_mode",
                [INTERNAL],
                {"internal", "changed_to_internal", "personless"},
                mode=PersonsOnEventsMode.DISABLED,
            ),
        ]
    )
    def test_rewrite_returns_the_rows_the_join_returns(
        self,
        _name: str,
        filters: list[dict],
        excluded: set[str],
        mode: PersonsOnEventsMode = JOINED,
        select: str = "SELECT event FROM events",
    ):
        joined, joined_sql = self._run(select, filters, mode, rewrite=False)
        rewritten, rewritten_sql = self._run(select, filters, mode, rewrite=True)

        assert joined == self.EVENTS - excluded
        assert rewritten == joined
        assert PERSONS_JOIN.search(joined_sql)
        assert not PERSONS_JOIN.search(rewritten_sql)
        assert "where_optimization" in rewritten_sql


class TestNegatedPersonFiltersPrinting(QueryMatchingTest, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.enterContext(
            patch(
                "posthog.clickhouse.materialized_columns.get_enabled_materialized_columns_by_table",
                return_value=MATERIALIZED_PERSON_COLUMNS,
            )
        )
        PropertyDefinition.objects.create(
            team=self.team, name="is_staff", type=PropertyDefinition.Type.PERSON, property_type=PropertyType.Boolean
        )

    def _print(
        self,
        select: str,
        filters: list[dict],
        mode: PersonsOnEventsMode = JOINED,
        materialization_mode: MaterializationMode | None = None,
    ) -> str:
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(
                self.team,
                HogQLQueryModifiers(
                    personsOnEventsMode=mode,
                    materializationMode=materialization_mode,
                    negatedPersonFiltersNotIn=True,
                ),
            ),
        )
        query = parse_select(f"{select} WHERE {{where}}", placeholders={"where": property_to_expr(filters, self.team)})
        sql, _ = prepare_and_print_ast(query, context, dialect="clickhouse")
        return sql

    def test_rewrite_reads_only_persons_that_ever_matched(self):
        sql = self._print("SELECT event FROM events", [INTERNAL, EXAMPLE])

        assert not PERSONS_JOIN.search(sql)
        assert "where_optimization" in sql
        self.assertQueryMatchesSnapshot(sql)

    @parameterized.expand(
        [
            param("positive_filter_alongside", [INTERNAL, {"key": "email", "type": "person", "operator": "is_set"}]),
            param("person_field_selected", [INTERNAL], select="SELECT event, person.properties.name FROM events"),
            param("boolean_property", [{"key": "is_staff", "type": "person", "operator": "is_not", "value": "true"}]),
            param("join_drops_rows_without_a_person", [INTERNAL], inner_join=True),
            param("properties_on_events", [INTERNAL], mode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
            param("not_events", [INTERNAL], select="SELECT distinct_id FROM person_distinct_ids"),
            param("property_not_materialized", [{**INTERNAL, "key": "$email"}]),
            param("persons_cte", [INTERNAL], select="WITH persons AS (SELECT 1 AS id) SELECT event FROM events"),
            param("materialization_disabled", [INTERNAL], materialization_mode=MaterializationMode.DISABLED),
        ]
    )
    def test_keeps_the_join_when_the_rewrite_would_not_drop_it(
        self,
        _name: str,
        filters: list[dict],
        select: str = "SELECT event FROM events",
        mode: PersonsOnEventsMode = JOINED,
        inner_join: bool = False,
        materialization_mode: MaterializationMode | None = None,
    ):
        with patch("posthog.hogql.database.schema.persons.posthoganalytics.feature_enabled", return_value=inner_join):
            sql = self._print(select, filters, mode, materialization_mode)

        assert "where_optimization" not in sql
        assert bool(PERSONS_JOIN.search(sql)) == (mode == JOINED)
