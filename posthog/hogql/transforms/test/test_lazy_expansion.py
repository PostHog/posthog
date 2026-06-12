from typing import Optional, cast

from posthog.test.base import BaseTest

from django.test import override_settings

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.lazy_expansion import ScopeDemand, collect_lazy_demand


class TestLazyDemandCollector(BaseTest):
    maxDiff = None

    def _demands(self, query: str, modifiers: Optional[HogQLQueryModifiers] = None) -> list[ScopeDemand]:
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=modifiers if modifiers is not None else HogQLQueryModifiers(),
        )
        context.database = Database.create_for(self.team.pk, modifiers=context.modifiers, team=self.team)
        node = cast(ast.SelectQuery, resolve_types(parse_select(query), context, "clickhouse"))
        return collect_lazy_demand(node, context, None)

    def test_no_lazy_references(self):
        assert self._demands("select event from events") == []

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_lazy_join_demand(self):
        demands = self._demands("select event, pdi.person_id from events")
        assert len(demands) == 1
        demand = demands[0]
        assert list(demand.joins_to_add.keys()) == ["events__pdi"]
        join = demand.joins_to_add["events__pdi"]
        assert join.from_table == "events"
        assert join.to_table == "events__pdi"
        assert join.fields_accessed == {"person_id": ["person_id"]}
        assert [(r.table_name, r.column_name) for r in demand.field_rewrites] == [("events__pdi", "person_id")]

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_chained_lazy_joins_with_join_key_closure(self):
        demands = self._demands("select event, pdi.person.id from events")
        assert len(demands) == 1
        demand = demands[0]
        assert list(demand.joins_to_add.keys()) == ["events__pdi", "events__pdi__person"]
        # The chained join's key must be projected out of the pdi expansion under a collision-prefixed alias.
        assert demand.joins_to_add["events__pdi"].fields_accessed == {"events__pdi___person_id": ["person_id"]}
        assert demand.joins_to_add["events__pdi__person"].fields_accessed == {"id": ["id"]}
        overrides = demand.constraint_overrides["events__pdi"]
        assert [(o.alias, o.chain_to_replace) for o in overrides] == [
            ("events__pdi___person_id", ["events__pdi", "person_id"])
        ]

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_properties_demanded_before_fields(self):
        demands = self._demands("select person.properties, person.properties.name from events")
        demand = demands[0]
        person_join = demand.joins_to_add["events__person"]
        assert list(person_join.fields_accessed.keys()) == ["properties___name", "properties"]
        assert person_join.fields_accessed["properties___name"] == ["properties", "name"]

    def test_lazy_table_demand(self):
        demands = self._demands("select id, properties.email from persons")
        demand = demands[0]
        assert list(demand.tables_to_add.keys()) == ["persons"]
        assert demand.tables_to_add["persons"].fields_accessed == {
            "properties___email": ["properties", "email"],
            "id": ["id"],
        }

    def test_lazy_table_without_fields(self):
        demands = self._demands("select count() from persons")
        demand = demands[0]
        assert demand.tables_to_add["persons"].fields_accessed == {}

    def test_lazy_table_alias(self):
        demands = self._demands("select p.id from persons as p")
        demand = demands[0]
        assert list(demand.tables_to_add.keys()) == ["p"]

    def test_demand_attaches_to_owning_scope(self):
        demands = self._demands("select event from events where distinct_id in (select distinct_id from person_distinct_ids)")
        assert len(demands) == 1
        assert list(demands[0].tables_to_add.keys()) == ["person_distinct_ids"]
        assert demands[0].select.select_from is not None
        table = demands[0].select.select_from.table
        assert isinstance(table, ast.Field) and table.chain == ["person_distinct_ids"]

    def test_wrap_detection_for_self_join_on_lazy_join_field(self):
        demands = self._demands(
            "select e.event from events e left join events e2 on e.person_id = e2.person_id",
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
        )
        demand = demands[0]
        assert demand.tables_to_wrap == {"e2"}
