from datetime import UTC, datetime
from typing import Any

from django.test import SimpleTestCase

import orjson
from parameterized import parameterized
from pydantic import BaseModel, ValidationError

from posthog.schema import HogQLFilters, HogQLQueryModifiers, HogQLVariable, PersonsOnEventsMode, SessionPropertyFilter

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, HogQLQuerySettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.property_access_types import RestrictedProperty

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.hogql_client.contract import ExecuteContext, ExecuteRequest


def _fields_set(request: ExecuteRequest) -> dict[str, set[str]]:
    passed = {name: getattr(request, name) for name in request.model_fields_set}
    return {"": set(passed)} | {
        name: value.model_fields_set for name, value in passed.items() if isinstance(value, BaseModel)
    }


class TestExecuteRequest(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "select_tree_and_placeholder",
                {
                    "query": parse_select("select event from events where timestamp > {since}"),
                    "placeholders": {"since": ast.Constant(value=datetime(2026, 1, 2, tzinfo=UTC))},
                },
            ),
            ("union_tree", {"query": parse_select("select 1 union all select 2")}),
            (
                "filter_whose_type_is_a_default",
                {
                    "filters": HogQLFilters(
                        properties=[SessionPropertyFilter(key="$entry_current_url", operator="exact", value="/")]
                    )
                },
            ),
            ("setting_that_clears_a_default", {"settings": HogQLGlobalSettings(max_execution_time=None)}),
            ("filters_with_nothing_set", {"filters": HogQLFilters()}),
            (
                "modifiers",
                {
                    "modifiers": HogQLQueryModifiers(
                        personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
                    )
                },
            ),
            ("variables", {"variables": {"limit": HogQLVariable(code_name="limit", variableId="1", value=5)}}),
            (
                "enums_and_direct_connection",
                {
                    "workload": Workload.OFFLINE,
                    "ch_user": ClickHouseUser.API,
                    "limit_context": LimitContext.EXPORT,
                    "connection_id": "source",
                    "send_raw_query": True,
                },
            ),
            ("none_passed_on_purpose", {"limit_context": None, "pretty": None}),
            (
                "context",
                {
                    "context": HogQLContext(
                        restricted_properties={RestrictedProperty(name="email", property_type=2)},
                        property_type_overrides={"plan": "String"},
                        globals={"plans": ["free", 1]},
                        limit_top_select=False,
                        bypass_warehouse_access_control=True,
                        modifiers=HogQLQueryModifiers(debug=True),
                    )
                },
            ),
        ]
    )
    def test_request_survives_json(self, _name: str, arguments: dict[str, Any]) -> None:
        sent = ExecuteRequest.from_call(**{"query": "select 1", **arguments})

        read = ExecuteRequest.model_validate_json(sent.to_json())

        assert read == sent
        assert _fields_set(read) == _fields_set(sent)

    @parameterized.expand(
        [
            ("nothing_else_passed", {}, {}),
            ("prebuilt_database", {"context": HogQLContext(database=Database())}, {"context": {}}),
            (
                "context_an_earlier_query_wrote_to",
                {"context": HogQLContext(values={"hogql_val_0": "x"}, referenced_saved_query_ids={"view"})},
                {"context": {}},
            ),
        ]
    )
    def test_sends_only_what_the_service_cannot_derive(
        self, _name: str, arguments: dict[str, Any], also_sent: dict[str, Any]
    ) -> None:
        sent = orjson.loads(ExecuteRequest.from_call("select 1", **arguments).to_json())

        assert sent == {"query": "select 1", **also_sent}

    @parameterized.expand(
        [
            ("argument_with_no_wire_form", {"resolver_factory": object()}),
            ("context_field_with_no_wire_form", {"context": HogQLContext(output_format="JSONEachRow")}),
            ("settings_of_another_class", {"settings": HogQLQuerySettings()}),
        ]
    )
    def test_refuses_what_cannot_cross(self, _name: str, arguments: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            ExecuteRequest.from_call("select 1", **arguments)

    def test_service_rebuilds_the_context_from_the_fields_that_crossed(self) -> None:
        restricted = {RestrictedProperty(name="email", property_type=2)}

        rebuilt = ExecuteContext(restricted_properties=restricted, limit_top_select=False).to_context(
            team_id=1, user=None
        )

        assert (rebuilt.team_id, rebuilt.restricted_properties, rebuilt.limit_top_select) == (1, restricted, False)
        assert rebuilt.apply_events_retention_floor is True
