import re
from typing import Any

import pytest
from posthog.test.base import BaseTest

from django.test import override_settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.models import PropertyDefinition
from posthog.models.group.util import create_group
from posthog.test.test_utils import create_group_type_mapping_without_created_at
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseJoin, DataWarehouseTable


class TestPropertyTypes(BaseTest):
    snapshot: Any
    maxDiff = None

    def setUp(self):
        super().setUp()
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "org1", "inty": 1},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_height",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_width",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="bool",
            defaults={"property_type": "Boolean"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="tickets",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="provided_timestamp",
            defaults={"property_type": "DateTime"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="$initial_browser",
            defaults={"property_type": "String"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.GROUP,
            name="inty",
            defaults={"property_type": "Numeric", "group_type_index": 0},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.GROUP,
            name="group_boolean",
            defaults={"property_type": "Boolean", "group_type_index": 0},
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_event(self):
        printed = self._print_select(
            "select properties.$screen_width * properties.$screen_height, properties.bool from events"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_person_raw(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_person(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_combined(self):
        printed = self._print_select("select properties.$screen_width * person.properties.tickets from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_event_person_poe_off(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_resolve_property_types_event_person_poe_on(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_property_types(self):
        printed = self._print_select("select organization.properties.inty from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_boolean_property_types(self):
        printed = self._print_select(
            """select
            organization.properties.group_boolean = true,
            organization.properties.group_boolean = false,
            organization.properties.group_boolean is null
            from events"""
        )
        assert printed == self.snapshot
        assert (
            "SELECT ifNull(equals(toBool(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL)), 1), 0), ifNull(equals(toBool(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL)), 0), 0), isNull(toBool(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL)))"
            in re.sub(r"%\(hogql_val_\d+\)s", "hogvar", printed)
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_types_are_the_same_in_persons_inlined_subselect(self):
        expr = parse_select(
            """select table_a.id from
                    (select
                        events.timestamp as id,
                        organization.properties.group_boolean = true,
                        organization.properties.group_boolean = false,
                        organization.properties.group_boolean is null
                    from events) as table_a
            join persons on table_a.id = persons.id and persons.id in (select
                        events.timestamp as id,
                        organization.properties.group_boolean = true,
                        organization.properties.group_boolean = false,
                        organization.properties.group_boolean is null
                    from events)"""
        )
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        query = re.sub(r"hogql_val_\d+", "hogql_val", query)
        # We're searching for the two subselects and making sure they are exactly the same
        results = re.findall(
            rf"SELECT toTimeZone\(events\.timestamp.*?WHERE equals\(events\.team_id, {self.team.id}\)\)", query
        )
        assert results[0] == results[1]

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_data_warehouse_person_property_types(self):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="extended_properties",
            columns={
                "string_prop": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
                "int_prop": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
                "bool_prop": {"hogql": "BooleanDatabaseField", "clickhouse": "Nullable(Bool)"},
            },
            credential=credential,
            url_pattern="",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="extended_properties",
            joining_table_key="string_prop",
            field_name="extended_properties",
        )

        printed = self._print_select(
            "select persons.extended_properties.string_prop, persons.extended_properties.int_prop, persons.extended_properties.bool_prop AS bool_prop from persons WHERE bool_prop = true"
        )

        assert printed == self.snapshot

    def _print_select(self, select: str):
        expr = parse_select(select)
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)
