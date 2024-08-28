import json
from inline_snapshot import snapshot

from hogvm.python.operation import HOGQL_BYTECODE_VERSION
from posthog.cdp.filters import hog_function_filters_to_expr
from posthog.hogql.bytecode import create_bytecode
from posthog.models.action.action import Action
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


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

        return json.loads(json.dumps(create_bytecode(res)))

    def test_filters_empty(self):
        assert self.filters_to_bytecode(filters={}) == snapshot(["_H", HOGQL_BYTECODE_VERSION, 29])

    def test_filters_all_events(self):
        assert self.filters_to_bytecode(
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
        ) == snapshot(["_H", HOGQL_BYTECODE_VERSION, 29, 3, 0, 4, 2])

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
                18,
                3,
                2,
                4,
                1,
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
                3,
                1,
                4,
                1,
            ]
        )

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
                18,
                3,
                5,
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
                "$current_url",
                32,
                "properties",
                1,
                2,
                17,
                3,
                2,
                3,
                4,
                4,
                2,
            ]
        )
