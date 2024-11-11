import json
from django.test import TestCase
from inline_snapshot import snapshot

from hogvm.python.operation import HOGQL_BYTECODE_VERSION
from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.user import User
from posthog.test.base import QueryMatchingTest


to_dict = lambda x: json.loads(json.dumps(x))


class TestHogFunction(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

    def test_hog_function_basic(self):
        item = HogFunction.objects.create(name="Test", team=self.team, type="destination")
        assert item.name == "Test"
        assert item.hog == ""
        assert not item.enabled

    def test_hog_function_team_no_filters_compilation(self):
        item = HogFunction.objects.create(name="Test", team=self.team, type="destination")

        # Some json serialization is needed to compare the bytecode more easily in tests
        json_filters = to_dict(item.filters)
        assert json_filters["bytecode"] == ["_H", HOGQL_BYTECODE_VERSION, 29]  # TRUE

    def test_hog_function_filters_compilation(self):
        item = HogFunction.objects.create(
            name="Test",
            type="destination",
            team=self.team,
            filters={
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "actions": [{"id": "9", "name": "Test Action", "type": "actions", "order": 1}],
                "filter_test_accounts": True,
            },
        )

        # Some json serialization is needed to compare the bytecode more easily in tests
        json_filters = to_dict(item.filters)
        assert json_filters == {
            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            "actions": [{"id": "9", "name": "Test Action", "type": "actions", "order": 1}],
            "filter_test_accounts": True,
            "bytecode": [
                "_H",
                HOGQL_BYTECODE_VERSION,
                32,
                "$host",
                32,
                "properties",
                1,
                2,
                2,
                "toString",
                1,
                32,
                "^(localhost|127\\.0\\.0\\.1)($|:)",
                2,
                "match",
                2,
                5,
                47,
                3,
                35,
                33,
                1,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                3,
                2,
                32,
                "$host",
                32,
                "properties",
                1,
                2,
                2,
                "toString",
                1,
                32,
                "^(localhost|127\\.0\\.0\\.1)($|:)",
                2,
                "match",
                2,
                5,
                47,
                3,
                35,
                33,
                1,
                33,
                2,
                33,
                1,
                11,
                3,
                2,
                4,
                2,
            ],
        }

    def test_hog_function_team_filters_only_compilation(self):
        item = HogFunction.objects.create(
            name="Test",
            type="destination",
            team=self.team,
            filters={
                "filter_test_accounts": True,
            },
        )

        # Some json serialization is needed to compare the bytecode more easily in tests
        json_filters = to_dict(item.filters)

        assert json.dumps(json_filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "$host", 32, "properties", 1, 2, 2, "toString", 1, 32, "^(localhost|127\\\\.0\\\\.0\\\\.1)($|:)", 2, "match", 2, 5, 47, 3, 35, 33, 1, 3, 1]'
        )


class TestHogFunctionsBackgroundReloading(TestCase, QueryMatchingTest):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

        self.action = Action.objects.create(
            team=self.team,
            name="Test Action",
            steps_json=[
                {
                    "event": "test-event",
                    "properties": [
                        {
                            "key": "prop-1",
                            "operator": "exact",
                            "value": "old-value-1",
                            "type": "event",
                        }
                    ],
                }
            ],
        )

        self.action2 = Action.objects.create(
            team=self.team,
            name="Test Action",
            steps_json=[
                {
                    "event": None,
                    "properties": [
                        {
                            "key": "prop-2",
                            "operator": "exact",
                            "value": "old-value-2",
                            "type": "event",
                        }
                    ],
                }
            ],
        )

    def test_hog_functions_reload_on_action_saved(self):
        hog_function_1 = HogFunction.objects.create(
            name="func 1",
            type="destination",
            team=self.team,
            filters={
                "actions": [
                    {"id": str(self.action.id), "name": "Test Action", "type": "actions", "order": 1},
                    {"id": str(self.action2.id), "name": "Test Action 2", "type": "actions", "order": 2},
                ],
            },
        )
        hog_function_2 = HogFunction.objects.create(
            name="func 2",
            type="destination",
            team=self.team,
            filters={
                "actions": [
                    {"id": str(self.action.id), "name": "Test Action", "type": "actions", "order": 1},
                ],
            },
        )

        # Check that the bytecode is correct
        assert json.dumps(hog_function_1.filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "test-event", 32, "event", 1, 1, 11, 32, "old-value-1", 32, "prop-1", 32, "properties", 1, 2, 11, 3, 2, 3, 1, 32, "old-value-2", 32, "prop-2", 32, "properties", 1, 2, 11, 3, 1, 4, 2]'
        )

        assert json.dumps(hog_function_2.filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "test-event", 32, "event", 1, 1, 11, 32, "old-value-1", 32, "prop-1", 32, "properties", 1, 2, 11, 3, 2, 3, 1, 4, 1]'
        )

        # Modify the action and check that the bytecode is updated
        self.action.steps_json = [
            {
                "event": "test-event",
                "properties": [
                    {
                        "key": "prop-1",
                        "operator": "exact",
                        "value": "change-value",
                        "type": "event",
                    }
                ],
            }
        ]
        # 1 update action, 1 load action, 1 load hog functions, 1 load all related actions, 1 bulk update hog functions
        with self.assertNumQueries(5):
            self.action.save()
        hog_function_1.refresh_from_db()
        hog_function_2.refresh_from_db()

        assert json.dumps(hog_function_1.filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "test-event", 32, "event", 1, 1, 11, 32, "change-value", 32, "prop-1", 32, "properties", 1, 2, 11, 3, 2, 3, 1, 32, "old-value-2", 32, "prop-2", 32, "properties", 1, 2, 11, 3, 1, 4, 2]'
        )
        assert json.dumps(hog_function_2.filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "test-event", 32, "event", 1, 1, 11, 32, "change-value", 32, "prop-1", 32, "properties", 1, 2, 11, 3, 2, 3, 1, 4, 1]'
        )

    def test_hog_functions_reload_on_team_saved(self):
        self.team.test_account_filters = []
        self.team.save()
        hog_function_1 = HogFunction.objects.create(
            name="func 1",
            type="destination",
            team=self.team,
            filters={
                "filter_test_accounts": True,
            },
        )
        hog_function_2 = HogFunction.objects.create(
            name="func 2",
            type="destination",
            team=self.team,
            filters={
                "filter_test_accounts": True,
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            },
        )
        hog_function_3 = HogFunction.objects.create(
            name="func 3",
            type="destination",
            team=self.team,
            filters={
                "filter_test_accounts": False,
            },
        )

        # Check that the bytecode is correct
        assert json.dumps(hog_function_1.filters["bytecode"]) == snapshot(f'["_H", {HOGQL_BYTECODE_VERSION}, 29]')
        assert json.dumps(hog_function_2.filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "$pageview", 32, "event", 1, 1, 11, 3, 1, 4, 1]'
        )
        assert json.dumps(hog_function_3.filters["bytecode"]) == snapshot(f'["_H", {HOGQL_BYTECODE_VERSION}, 29]')

        # Modify the action and check that the bytecode is updated
        self.team.test_account_filters = [
            {"key": "$host", "operator": "regex", "value": "^(localhost|127\\.0\\.0\\.1)($|:)"},
            {"key": "$pageview", "operator": "regex", "value": "test"},
        ]
        # 1 update team, 1 load hog functions, 1 update hog functions
        with self.assertNumQueries(3):
            self.team.save()
        hog_function_1.refresh_from_db()
        hog_function_2.refresh_from_db()
        hog_function_3.refresh_from_db()

        assert json.dumps(hog_function_1.filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "$host", 32, "properties", 1, 2, 2, "toString", 1, 32, "^(localhost|127\\\\.0\\\\.0\\\\.1)($|:)", 2, "match", 2, 47, 3, 35, 33, 0, 32, "$pageview", 32, "properties", 1, 2, 2, "toString", 1, 32, "test", 2, "match", 2, 47, 3, 35, 33, 0, 3, 2]'
        )
        assert json.dumps(hog_function_2.filters["bytecode"]) == snapshot(
            f'["_H", {HOGQL_BYTECODE_VERSION}, 32, "$host", 32, "properties", 1, 2, 2, "toString", 1, 32, "^(localhost|127\\\\.0\\\\.0\\\\.1)($|:)", 2, "match", 2, 47, 3, 35, 33, 0, 32, "$pageview", 32, "properties", 1, 2, 2, "toString", 1, 32, "test", 2, "match", 2, 47, 3, 35, 33, 0, 32, "$pageview", 32, "event", 1, 1, 11, 3, 3, 4, 1]'
        )
        assert json.dumps(hog_function_3.filters["bytecode"]) == snapshot(f'["_H", {HOGQL_BYTECODE_VERSION}, 29]')
