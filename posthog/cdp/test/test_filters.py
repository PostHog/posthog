import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from inline_snapshot import snapshot

from posthog.hogql.compiler.bytecode import create_bytecode

from posthog.cdp.filters import compile_filters_bytecode, hog_function_filters_to_expr
from posthog.models.action.action import Action

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


class TestHogFunctionFilters(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    action: Action
    filters: dict

    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(
            team=self.team,
            name="test action",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()

        self.filters = {
            "events": [
                {
                    "id": "$pageview",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": "url", "value": "docs", "operator": "icontains", "type": "event"}],
                }
            ],
            "actions": [{"id": f"{self.action.id}", "name": "Test Action", "type": "actions", "order": 1}],
            "properties": [
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "icontains",
                    "type": "person",
                },
                {
                    "key": "name",
                    "value": "ben",
                    "operator": "exact",
                    "type": "person",
                },
            ],
            "filter_test_accounts": True,
        }

    def filters_to_bytecode(self, filters: dict):
        res = hog_function_filters_to_expr(filters=filters, team=self.team, actions={self.action.id: self.action})

        return json.loads(json.dumps(create_bytecode(res).bytecode))

    def test_filters_empty(self):
        bytecode = self.filters_to_bytecode(filters={})
        assert bytecode == snapshot(["_H", HOGQL_BYTECODE_VERSION, 29])
        assert execute_bytecode(bytecode, {}).result is True

    def test_filters_all_events(self):
        bytecode = self.filters_to_bytecode(
            filters={
                "events": [
                    {
                        "id": None,
                        "name": "All events",
                        "type": "events",
                        "order": 0,
                    }
                ]
            }
        )
        assert bytecode == snapshot(["_H", HOGQL_BYTECODE_VERSION, 29])

        assert execute_bytecode(bytecode, {}).result is True

    def test_filters_raises_on_select(self):
        response = compile_filters_bytecode(
            filters={
                "properties": [
                    {
                        "type": "hogql",
                        "key": "(select 1)",
                    }
                ]
            },
            team=self.team,
        )
        assert response["bytecode_error"] == "Select queries are not allowed in filters"

    def test_filters_events(self):
        bytecode = self.filters_to_bytecode(filters={"events": self.filters["events"]})
        assert bytecode == snapshot(
            [
                "_H",
                HOGQL_BYTECODE_VERSION,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                32,
                "%docs%",
                32,
                "url",
                32,
                "properties",
                1,
                2,
                2,
                "toString",
                1,
                18,
                3,
                2,
            ]
        )

    def test_filters_actions(self):
        bytecode = self.filters_to_bytecode(filters={"actions": self.filters["actions"]})
        assert bytecode == snapshot(
            [
                "_H",
                HOGQL_BYTECODE_VERSION,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                32,
                "%docs%",
                32,
                "$current_url",
                32,
                "properties",
                1,
                2,
                17,
                3,
                2,
            ]
        )

        # Also works if we don't pass the actions dict
        expr = hog_function_filters_to_expr(filters={"actions": self.filters["actions"]}, team=self.team, actions={})
        bytecode_2 = create_bytecode(expr).bytecode
        assert bytecode == bytecode_2

    def test_filters_properties(self):
        assert self.filters_to_bytecode(filters={"properties": self.filters["properties"]}) == snapshot(
            [
                "_H",
                HOGQL_BYTECODE_VERSION,
                32,
                "%@posthog.com%",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                2,
                "toString",
                1,
                18,
                32,
                "ben",
                32,
                "name",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                11,
                3,
                2,
            ]
        )

    def test_filters_full(self):
        bytecode = self.filters_to_bytecode(filters=self.filters)
        assert bytecode == snapshot(
            [
                "_H",
                HOGQL_BYTECODE_VERSION,
                32,
                "%@posthog.com%",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                2,
                "toString",
                1,
                20,
                32,
                "%@posthog.com%",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                2,
                "toString",
                1,
                18,
                32,
                "ben",
                32,
                "name",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                11,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                32,
                "%docs%",
                32,
                "url",
                32,
                "properties",
                1,
                2,
                2,
                "toString",
                1,
                18,
                3,
                2,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                32,
                "%docs%",
                32,
                "$current_url",
                32,
                "properties",
                1,
                2,
                17,
                3,
                2,
                4,
                2,
                3,
                4,
            ]
        )
