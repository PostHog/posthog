import re
import json
from typing import Any
from uuid import UUID

import pytest
from posthog.test.base import (
    BaseTest,
    NewEventsSchemaSnapshotExtension,
    _create_event,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, SessionsV2JoinMode, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import (
    Database,
    _use_person_id_from_person_overrides,
    _use_person_properties_from_events,
)
from posthog.hogql.database.lazy_join_tags import PERSONS
from posthog.hogql.database.models import LazyJoin, VirtualTable
from posthog.hogql.database.schema.traffic_type import create_is_bot_field
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.property_metadata import PropertyMetadata
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.models import Organization, PropertyDefinition, Team

from products.data_tools.backend.models.join import DataWarehouseJoin


class TestNamespacedLazyTables(SimpleTestCase):
    @parameterized.expand(
        [
            ("persons_star", "persons", "SELECT * FROM {table} LIMIT 1"),
            ("persons_count", "persons", "SELECT count() FROM {table}"),
            ("persons_id", "persons", "SELECT id FROM {table}"),
            ("persons_property", "persons", "SELECT properties.email FROM {table}"),
            ("persons_qualified_field", "persons", "SELECT {table}.id FROM {table}"),
            ("persons_alias", "persons", "SELECT p.id, p.properties.email FROM {table} AS p"),
            ("persons_cte", "persons", "WITH people AS (SELECT id FROM {table}) SELECT id FROM people"),
            ("persons_join", "persons", "SELECT p.id FROM {table} AS p JOIN {table} AS q ON p.id = q.id"),
            ("groups_star", "groups", "SELECT * FROM {table} LIMIT 1"),
            ("groups_count", "groups", "SELECT count() FROM {table}"),
            ("groups_key", "groups", "SELECT key FROM {table}"),
            ("groups_property", "groups", "SELECT properties.name FROM {table}"),
            ("groups_alias", "groups", "SELECT g.key FROM {table} AS g"),
        ]
    )
    def test_namespaced_table_matches_unqualified_table(self, _name: str, table: str, query: str) -> None:
        expected = self._compile(query.format(table=table))
        actual = self._compile(query.format(table=f"posthog.{table}"))
        self.assertEqual(actual.replace(f"posthog__{table}", table), expected)

    def _compile(self, query: str) -> str:
        context = HogQLContext(
            team_id=1,
            team=Team(id=1, organization=Organization()),
            database=Database(),
            enable_select_queries=True,
            use_new_events_schema=False,
            apply_events_retention_floor=False,
            restricted_properties=set(),
        )
        with patch("posthog.hogql.transforms.property_types.load_property_metadata", return_value=PropertyMetadata()):
            return prepare_and_print_ast(parse_select(query), context, "clickhouse")[0]


WRAPPED_JOIN = "FROM events AS initial JOIN events AS joined ON initial.person_id = joined.person_id"
# The wrapper exports these for the join's own person-ID correction, whatever the query reads.
JOIN_KEY_EXPORTS = {"override___distinct_id", "override___person_id", "event_person_id"}
BUILT_IN_FIELDS = (
    "$session_id",
    "$window_id",
    "$session_id_uuid",
    "$group_0",
    "$group_1",
    "$group_2",
    "$group_3",
    "$group_4",
)


class TestWrappedEventJoins(SimpleTestCase):
    @parameterized.expand([("legacy", False), ("native", True)])
    def test_reads_exported_columns(self, _name: str, native: bool) -> None:
        printed, _ = self._compile(
            "SELECT " + ", ".join(f"joined.{field}" for field in BUILT_IN_FIELDS) + f" {WRAPPED_JOIN}", native=native
        )
        outer_select = printed.split(" FROM ", 1)[0]
        for field in BUILT_IN_FIELDS:
            assert f"joined.`{field}` AS `{field}`" in outer_select, printed
        assert "JOIN (SELECT" in printed

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_converts_each_outer_read_of_a_raw_property_export(self, _name: str, native: bool) -> None:
        printed, _ = self._compile(
            "SELECT joined.properties.amount, toFloatOrZero(joined.properties.amount), "
            "toFloatOrZero(toString(joined.properties.amount)), joined.properties.enabled, "
            f"joined.properties.scheduled_at {WRAPPED_JOIN}",
            native=native,
        )
        outer = printed.split(" FROM ", 1)[0]
        assert "accurateCastOrNull(joined.properties___amount, %(hogql_val_" in outer
        assert "toFloat64OrZero(joined.properties___amount)" in outer
        assert "toFloat64OrZero(toString(accurateCastOrNull(joined.properties___amount, %(hogql_val_" in outer
        assert "transform(toString(joined.properties___enabled), %(hogql_val_" in outer
        assert "parseDateTime64BestEffortOrNull(joined.properties___scheduled_at, 6, %(hogql_val_" in outer
        inner = self._wrapper_select_list(printed, "joined", native)
        assert inner.count("AS properties___amount") == 1
        assert "accurateCastOrNull" not in inner
        assert "parseDateTime64BestEffortOrNull" not in inner
        if native:
            assert "joined.properties.amount" in inner
            assert "JSONExtractKeysAndValuesRaw" not in inner
        else:
            assert "JSONExtractRaw(joined.properties, %(hogql_val_" in inner

    @parameterized.expand(
        [
            ("key", "joined.properties.amount", "", {"properties___amount"}),
            ("document", "joined.properties", "", {"properties"}),
            ("document_to_string", "toString(joined.properties)", "", {"properties"}),
            (
                "document_and_key",
                "joined.properties, joined.properties.amount",
                "",
                {"properties", "properties___amount"},
            ),
            ("where_only", "count()", "WHERE joined.properties.amount > 1", {"properties___amount"}),
            ("order_by_only", "joined.uuid", "ORDER BY joined.properties.amount", {"uuid", "properties___amount"}),
        ]
    )
    def test_exports_the_document_only_for_whole_document_reads(
        self, _name: str, select: str, clause: str, expected: set[str]
    ) -> None:
        for native in (False, True):
            printed, _ = self._compile(f"SELECT {select} {WRAPPED_JOIN} {clause}", native=native)
            assert self._exports(printed, "joined", native) == expected, printed

    def test_decides_exports_per_source(self) -> None:
        printed, _ = self._compile(
            "SELECT b.properties, c.properties.amount FROM events AS a "
            "JOIN events AS b ON a.person_id = b.person_id JOIN events AS c ON a.person_id = c.person_id"
        )
        assert self._exports(printed, "b", native=False) == {"properties"}
        assert self._exports(printed, "c", native=False) == {"properties___amount"}

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_exports_expression_field_dependencies(self, _name: str, native: bool) -> None:
        printed, _ = self._compile(f"SELECT joined.$virt_is_bot {WRAPPED_JOIN}", native=native)
        assert {"properties___$raw_user_agent", "properties___$ip"} <= self._exports(printed, "joined", native)
        assert "joined.properties," not in printed.split(" FROM ", 1)[0]

    def test_converts_a_key_read_through_a_document_alias(self) -> None:
        printed, _ = self._compile(f"SELECT joined.properties AS p, p.amount + 1 {WRAPPED_JOIN}")
        assert printed.startswith(
            "SELECT joined.properties AS p, plus(accurateCastOrNull(joined.properties___amount, %(hogql_val_"
        ), printed
        assert self._exports(printed, "joined", native=False) == {"properties", "properties___amount"}

    def test_wraps_a_schema_qualified_table_without_an_alias(self) -> None:
        printed, _ = self._compile(
            "SELECT initial.event, posthog.events.properties.amount FROM events AS initial "
            "JOIN posthog.events ON initial.person_id = posthog.events.person_id"
        )
        assert "accurateCastOrNull(posthog__events.properties___amount, %(hogql_val_" in printed.split(" FROM ", 1)[0]
        assert ") AS posthog__events ON equals(" in printed

    def test_wraps_a_join_whose_constraint_needs_the_identity_join(self) -> None:
        printed, _ = self._compile(f"SELECT joined.event {WRAPPED_JOIN}", person_overrides=False)
        assert self._exports(printed, "joined", native=False) == {"pdi___person_id", "event"}
        assert "AS joined__pdi ON equals(joined.distinct_id, joined__pdi.distinct_id)" in printed
        assert printed.endswith(
            "AS joined ON equals(initial__pdi.person_id, joined.pdi___person_id) WHERE equals(initial.team_id, 1) LIMIT 50000"
        )

    def test_corrects_the_person_id_inside_the_wrapper_only(self) -> None:
        printed, _ = self._compile(f"SELECT joined.person_id {WRAPPED_JOIN}")
        assert printed.startswith(
            "SELECT if(not(empty(joined.override___distinct_id)), joined.override___person_id, "
            "joined.event_person_id) AS person_id FROM"
        )
        assert printed.count("AS joined__override ON") == 1

    @parameterized.expand([("identity_join", False), ("person_overrides", True)])
    def test_converts_the_exported_timestamp_inside_the_wrapper(self, _name: str, person_overrides: bool) -> None:
        printed, _ = self._compile(
            "SELECT e.timestamp FROM events e LEFT JOIN events e2 "
            "ON e.person_id = e2.person_id AND e2.timestamp >= e.timestamp "
            "WHERE e.timestamp >= '2024-03-01' AND e.timestamp < '2024-04-01'",
            person_overrides=person_overrides,
            timezone="America/New_York",
            modifiers=HogQLQueryModifiers(pushDownPredicates=False),
        )
        assert re.search(r"toTimeZone\(e2\.timestamp, %\(hogql_val_\d+\)s\) AS timestamp", printed), printed
        assert re.search(r"greaterOrEquals\(e2\.timestamp, toTimeZone\(e\.timestamp,", printed), printed
        assert re.search(r"greaterOrEquals\(e\.timestamp, ", printed), printed
        assert re.search(r"less\(e\.timestamp, ", printed), printed

    def test_keeps_property_paths_distinct(self) -> None:
        printed, context = self._compile(
            f"SELECT joined.properties.a.b, joined.properties.a___b, joined.properties.arr[1] {WRAPPED_JOIN}"
        )
        assert self._exports(printed, "joined", native=False) == {
            "properties___a___b",
            "properties___a___b_2",
            "properties___arr___1",
        }
        assert 1 in context.values.values()
        assert "1" not in context.values.values()

    def test_keeps_nested_scopes_apart(self) -> None:
        printed, _ = self._compile(
            "SELECT (SELECT count() FROM events AS joined WHERE joined.properties.amount > 1) AS nested, "
            f"joined.properties.amount {WRAPPED_JOIN}"
        )
        outer = printed.split(" FROM events AS initial", 1)[0]
        assert "JSONExtractRaw(joined.properties, %(hogql_val_" in outer
        assert "accurateCastOrNull(joined.properties___amount, %(hogql_val_" in outer

        printed, _ = self._compile(f"SELECT x.v FROM (SELECT joined.properties.amount AS v {WRAPPED_JOIN}) AS x")
        assert printed.startswith("SELECT x.v AS v FROM (SELECT accurateCastOrNull(joined.properties___amount, ")
        assert "AS properties___amount" in printed

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_reads_person_properties_through_the_wrapper(self, _name: str, native: bool) -> None:
        printed, _ = self._compile(
            f"SELECT joined.person.properties.age {WRAPPED_JOIN}", native=native, person_properties="on_events"
        )
        assert printed.startswith("SELECT accurateCastOrNull(joined.poe___properties___age, %(hogql_val_")
        assert "joined.person_properties" in self._wrapper_select_list(printed, "joined", native)

        printed, _ = self._compile(
            f"SELECT joined.person.properties.age {WRAPPED_JOIN}", native=native, person_properties="joined"
        )
        assert printed.startswith("SELECT joined.person___properties___age AS age FROM")
        assert printed.count("accurateCastOrNull") == 1
        assert "AS joined__person ON" in printed

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_keeps_property_restrictions_inside_the_wrapper(self, _name: str, native: bool) -> None:
        restricted = {RestrictedProperty(name="amount", property_type=PropertyDefinition.Type.EVENT)}
        printed, _ = self._compile(
            f"SELECT joined.properties.amount, joined.properties.label {WRAPPED_JOIN}",
            native=native,
            restricted=restricted,
        )
        inner = self._wrapper_select_list(printed, "joined", native)
        assert "NULL AS properties___amount" in inner
        assert "AS properties___label" in inner and "NULL AS properties___label" not in inner

        printed, _ = self._compile(f"SELECT joined.properties {WRAPPED_JOIN}", native=native, restricted=restricted)
        assert "JSONDropKeysPool(" in self._wrapper_select_list(printed, "joined", native)

    def _compile(
        self,
        query: str,
        native: bool = False,
        person_properties: str | None = None,
        restricted: set[RestrictedProperty] | None = None,
        person_overrides: bool = True,
        timezone: str = "UTC",
        modifiers: HogQLQueryModifiers | None = None,
    ) -> tuple[str, HogQLContext]:
        database = Database(timezone=timezone)
        events = database.get_table("events")
        events.fields["$virt_is_bot"] = create_is_bot_field(name="$virt_is_bot")
        if person_overrides:
            _use_person_id_from_person_overrides(database)
        if person_properties == "on_events":
            _use_person_properties_from_events(database)
            poe = events.fields["poe"]
            assert isinstance(poe, VirtualTable)
            poe.fields["id"] = events.fields["person_id"]
        elif person_properties == "joined":
            events.fields["person"] = LazyJoin(
                from_field=["person_id"], join_table=database.get_table("persons"), resolver=PERSONS
            )
        context = HogQLContext(
            team_id=1,
            team=Team(id=1, organization=Organization(), timezone=timezone),
            database=database,
            enable_select_queries=True,
            use_new_events_schema=native,
            apply_events_retention_floor=False,
            restricted_properties=restricted or set(),
            modifiers=modifiers or HogQLQueryModifiers(),
        )
        metadata = PropertyMetadata(
            event_properties={
                "amount": {"type": "Numeric"},
                "enabled": {"type": "Boolean"},
                "scheduled_at": {"type": "DateTime"},
            },
            person_properties={"age": {"type": "Numeric"}},
        )
        with patch("posthog.hogql.transforms.property_types.load_property_metadata", return_value=metadata):
            printed, _ = prepare_and_print_ast(parse_select(query), context, "clickhouse")
        return printed, context

    def _wrapper_select_list(self, printed: str, alias: str, native: bool) -> str:
        events_table = "events_json" if native else "events"
        head = printed.split(f" FROM {events_table} AS {alias} ", 1)[0]
        return head.rsplit("JOIN (SELECT ", 1)[1]

    def _exports(self, printed: str, alias: str, native: bool) -> set[str]:
        select_list = self._wrapper_select_list(printed, alias, native)
        names = {name.strip("`") for name in re.findall(r" AS (`[^`]+`|\w+)", select_list)}
        return names - JOIN_KEY_EXPORTS


class TestLazyJoins(BaseTest):
    snapshot: Any
    maxDiff = None

    @parameterized.expand(
        [
            (
                "values",
                "related.$session_id, related.properties.label, related.properties.amount, "
                "related.properties.enabled, toString(related.properties.scheduled_at)",
                ("00000000-0000-4000-8000-000000000002", "ready", 7.0, True, "2024-01-02 03:04:05.000000"),
            ),
            (
                "aggregates",
                "sum(related.properties.amount), countIf(related.properties.enabled), "
                "toString(max(related.properties.scheduled_at))",
                (7.0, 1, "2024-01-02 03:04:05.000000"),
            ),
            (
                "mixed_contexts_on_text",
                "related.properties.rating, toFloatOrZero(related.properties.rating)",
                (None, 0.0),
            ),
            (
                "paths",
                "related.properties.a.b, related.properties.a___b, related.properties.arr[1]",
                ("nested", "flat", "first"),
            ),
            (
                "window",
                "sum(related.properties.amount) OVER (PARTITION BY related.$session_id)",
                (7.0,),
            ),
        ]
    )
    def test_wrapped_events_join_executes_exported_property_reads(
        self, _name: str, select: str, expected: tuple[object, ...]
    ) -> None:
        for name, property_type in [
            ("amount", "Numeric"),
            ("rating", "Numeric"),
            ("enabled", "Boolean"),
            ("scheduled_at", "DateTime"),
        ]:
            PropertyDefinition.objects.create(team=self.team, name=name, property_type=property_type)
        event_uuid = _create_event(
            team=self.team,
            event="joined-event",
            distinct_id="joined-user",
            person_id=UUID("00000000-0000-4000-8000-000000000001"),
            properties={
                "$session_id": "00000000-0000-4000-8000-000000000002",
                "label": "ready",
                "amount": "7",
                "rating": "seven",
                "enabled": "true",
                "scheduled_at": "2024-01-02T03:04:05Z",
                "a": {"b": "nested"},
                "a___b": "flat",
                "arr": ["first", "second"],
            },
        )
        result = execute_hogql_query(
            f"SELECT {select} FROM events AS source "
            "JOIN events AS related ON source.person_id = related.person_id "
            "WHERE source.uuid = {event_uuid} AND related.uuid = {event_uuid}",
            team=self.team,
            placeholders={"event_uuid": ast.Constant(value=event_uuid)},
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert [tuple(row) for row in result.results] == [expected]

    def test_wrapped_events_join_converts_a_key_read_through_a_document_alias(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="amount", property_type="Numeric")
        event_uuid = _create_event(
            team=self.team,
            event="priced",
            distinct_id="user",
            person_id=UUID("00000000-0000-4000-8000-000000000001"),
            properties={"amount": "7"},
        )
        result = execute_hogql_query(
            "SELECT related.properties AS p, p.amount + 1 FROM events AS source "
            "JOIN events AS related ON source.person_id = related.person_id "
            "WHERE source.uuid = {event_uuid} AND related.uuid = {event_uuid}",
            team=self.team,
            placeholders={"event_uuid": ast.Constant(value=event_uuid)},
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert [(json.loads(document)["amount"], value) for document, value in result.results] == [("7", 8.0)]

    def test_wrapped_events_join_reads_each_alias_from_its_own_source(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="amount", property_type="Numeric")
        person_id = UUID("00000000-0000-4000-8000-000000000001")
        first = _create_event(
            team=self.team, event="first", distinct_id="user", person_id=person_id, properties={"amount": "7"}
        )
        second = _create_event(
            team=self.team, event="second", distinct_id="user", person_id=person_id, properties={"amount": "11"}
        )
        result = execute_hogql_query(
            "SELECT b.properties.amount, c.properties.amount, JSONExtractKeys(c.properties) FROM events AS a "
            "JOIN events AS b ON a.person_id = b.person_id JOIN events AS c ON a.person_id = c.person_id "
            "WHERE a.uuid = {first} AND b.uuid = {first} AND c.uuid = {second}",
            team=self.team,
            placeholders={"first": ast.Constant(value=first), "second": ast.Constant(value=second)},
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert [tuple(row) for row in result.results] == [(7.0, 11.0, ["amount"])]

    def test_wrapped_events_join_corrects_the_person_id_inside_the_wrapper(self) -> None:
        merged_from = _create_event(
            team=self.team,
            event="before-merge",
            distinct_id="merged_from",
            person_id=UUID("00000000-0000-4000-8000-000000000001"),
        )
        merged_to = _create_event(
            team=self.team,
            event="after-merge",
            distinct_id="merged_to",
            person_id=UUID("00000000-0000-4000-8000-000000000002"),
        )
        flush_persons_and_events()
        create_person_id_override_by_distinct_id("merged_from", "merged_to", self.team.pk)

        result = execute_hogql_query(
            "SELECT related.distinct_id, related.person_id FROM events AS source "
            "JOIN events AS related ON source.person_id = related.person_id "
            "WHERE source.uuid = {merged_to} AND related.uuid = {merged_from}",
            team=self.team,
            placeholders={"merged_from": ast.Constant(value=merged_from), "merged_to": ast.Constant(value=merged_to)},
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert [tuple(row) for row in result.results] == [("merged_from", UUID("00000000-0000-4000-8000-000000000002"))]

    def test_wrapped_events_left_join_keeps_unmatched_rows(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="amount", property_type="Numeric")
        event_uuid = _create_event(
            team=self.team,
            event="alone",
            distinct_id="user",
            person_id=UUID("00000000-0000-4000-8000-000000000001"),
            properties={"amount": "7"},
        )
        result = execute_hogql_query(
            "SELECT source.event, related.properties.amount, related.event FROM events AS source "
            "LEFT JOIN events AS related ON source.person_id = related.person_id AND related.event = 'other' "
            "WHERE source.uuid = {event_uuid}",
            team=self.team,
            placeholders={"event_uuid": ast.Constant(value=event_uuid)},
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert [tuple(row) for row in result.results] == [("alone", None, "")]

    def _schema_snapshot(self, printed: str):
        self.snapshot.session.pytest_session.config.option.warn_unused_snapshots = True
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA and "events_json" in printed:
            return self.snapshot(name="new_events_schema", extension_class=NewEventsSchemaSnapshotExtension)
        return self.snapshot

    def _assert_matches_snapshot(self, printed: str) -> None:
        assert printed == self._schema_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_tables(self):
        printed = self._print_select("select event, pdi.person_id from events")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_traversed_fields(self):
        printed = self._print_select("select event, person_id from events")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_tables_two_levels(self):
        printed = self._print_select("select event, pdi.person.id from events")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_two_levels_traversed(self):
        printed = self._print_select("select event, person.id from events")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_one_level_properties(self):
        printed = self._print_select("select person.properties.$browser from person_distinct_ids")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_one_level_properties_deep(self):
        printed = self._print_select("select person.properties.$browser.in.json from person_distinct_ids")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_tables_two_levels_properties(self):
        printed = self._print_select("select event, pdi.person.properties.$browser from events")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_two_levels_properties_duplicate(self):
        printed = self._print_select("select event, person.properties, person.properties.name from events")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_table_as_select_table(self):
        printed = self._print_select("select id, properties.email, properties.$browser from persons")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_table_as_table_in_join(self):
        printed = self._print_select(
            "select event, distinct_id, events.person_id, persons.properties.email from events left join persons on persons.id = events.person_id limit 10"
        )
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_select_count_from_lazy_table(self):
        printed = self._print_select("select count() from persons")
        self._assert_matches_snapshot(printed)

    def test_sample_on_lazy_table_is_stripped(self):
        # A lazy table expands into an aggregating subquery; ClickHouse rejects a SAMPLE modifier on
        # a subquery, so it must be dropped rather than left to produce invalid SQL — but not
        # silently: the user asked for sampling and needs to know it did not apply.
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=HogQLQueryModifiers())
        expr = parse_select("select session_id, $channel_type from sessions SAMPLE 10")
        printed, _ = prepare_and_print_ast(expr, context, "clickhouse")
        assert "SAMPLE" not in printed
        assert [warning.message for warning in context.warnings] == [
            'SAMPLE clause ignored: the "sessions" table is computed on the fly and cannot be sampled'
        ]

    @parameterized.expand(
        [
            ("v3", HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V3)),
            (
                "v2_uuid_join",
                HogQLQueryModifiers(
                    sessionTableVersion=SessionTableVersion.V2, sessionsV2JoinMode=SessionsV2JoinMode.UUID
                ),
            ),
        ]
    )
    def test_join_from_a_lazy_join_reads_the_extra_source_field_it_declares(
        self, _name: str, modifiers: HogQLQueryModifiers
    ):
        printed = self._print_select("SELECT events.session.$session_duration FROM session_replay_events", modifiers)

        assert "$session_id_uuid" in printed

    def _print_select(self, select: str, modifiers: HogQLQueryModifiers | None = None):
        expr = parse_select(select)
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=modifiers if modifiers is not None else HogQLQueryModifiers(),
            ),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_lazy_join_on_lazy_table(self):
        DataWarehouseJoin(
            team=self.team,
            source_table_name="cohort_people",
            source_table_key="person_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="new_person",
        ).save()

        printed = self._print_select("select new_person.id from cohort_people")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_lazy_join_on_lazy_table_with_properties(self):
        DataWarehouseJoin(
            team=self.team,
            source_table_name="cohort_people",
            source_table_key="person_id",
            joining_table_name="persons",
            joining_table_key="properties.email",
            field_name="new_person",
        ).save()

        printed = self._print_select("select new_person.id from cohort_people")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_lazy_join_on_lazy_table_with_person_properties(self):
        DataWarehouseJoin(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="events",
            joining_table_key="event",
            field_name="events",
        ).save()

        printed = self._print_select("select events.event from persons")
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_table_indirectly_referenced(self):
        # Ensures that the override table is added as a join, even when it is
        # only indirectly referenced in the query as part of the join constraint
        # of a lazy join.
        printed = self._print_select(
            "select person.id from events",
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        )
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_table_indirect_duplicate_references(self):
        # Ensures that the override table is only joined one time, even when it
        # is referenced via two different selected columns.
        printed = self._print_select(
            "select person_id, person.properties from events",
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        )
        self._assert_matches_snapshot(printed)

    def test_person_override_join_ordered_before_dependent_warehouse_joins(self):
        # A data-warehouse join keyed on `person_id` produces an ON constraint that references the
        # person-overrides join (`e__override`). When another warehouse join that does *not* depend
        # on the override is emitted between the events table and the override join, the override
        # join must still come before the dependent one: ClickHouse resolves joins left-to-right, so
        # a forward reference to `e__override` throws "Unknown identifier". Regression test for an
        # aliased events actors query that produced exactly that broken ordering.
        DataWarehouseJoin(
            team=self.team,
            source_table_name="events",
            source_table_key="event",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="event_link",
        ).save()
        DataWarehouseJoin(
            team=self.team,
            source_table_name="events",
            source_table_key="person_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="person_link",
        ).save()

        printed = self._print_select(
            "SELECT e.person_id AS actor_id, e.event_link.id AS a, e.person_link.id AS b FROM events AS e",
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
        )

        flat = " ".join(printed.split())
        override_pos = flat.find("AS e__override ON")
        dependent_pos = flat.find("AS e__person_link ON")
        assert override_pos != -1, "person-overrides join was not emitted"
        assert dependent_pos != -1, "person_id-keyed warehouse join was not emitted"
        # Guard against a vacuous assertion: the dependent join's ON must actually reference the override.
        assert "e__override." in flat[dependent_pos : dependent_pos + 300]
        assert override_pos < dependent_pos, "override join must be emitted before the join that references it"

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_session_join_with_timestamp_filter(self):
        # Documents SQL generation for events with session access and a timestamp filter.
        printed = self._print_select(
            "SELECT event, session.$session_duration "
            "FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08'"
        )
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_sessions_join_with_alias(self):
        # Documents that events table alias is propagated.
        printed = self._print_select(
            "SELECT event, session.$session_duration "
            "FROM events AS e "
            "WHERE e.timestamp >= '2024-01-01' AND event = 'my-event'"
        )
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_session_join_with_multiple_predicates(self):
        # Documents events query with session access and multiple event-level predicates.
        printed = self._print_select(
            "SELECT event, session.$session_duration "
            "FROM events "
            "WHERE timestamp >= '2024-01-01' "
            "AND timestamp < '2024-01-08' "
            "AND event = '$pageview' "
            "AND $session_id IS NOT NULL"
        )
        self._assert_matches_snapshot(printed)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_session_join_with_session_duration_filter(self):
        # Documents that session duration filters remain in outer WHERE (can't be pushed down).
        printed = self._print_select(
            "SELECT event, session.$session_duration "
            "FROM events "
            "WHERE timestamp >= '2024-01-01' "
            "AND session.$session_duration > 0"
        )
        self._assert_matches_snapshot(printed)
