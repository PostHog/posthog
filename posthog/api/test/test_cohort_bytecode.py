from typing import Any

from posthog.test.base import APIBaseTest

from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


class TestCohortBytecodeScenarios(APIBaseTest):
    def _create_and_fetch(self, name: str, filters: dict[str, Any]):
        from posthog.models.cohort.cohort import Cohort

        resp = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": name, "filters": filters},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        cohort = Cohort.objects.get(id=resp.json()["id"])
        return cohort

    def _patch_and_fetch(self, cohort_id: int, filters: dict[str, Any]):
        from posthog.models.cohort.cohort import Cohort

        resp = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}/",
            {"filters": filters},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        cohort = Cohort.objects.get(id=cohort_id)
        return cohort

    def test_and_filter_realtime(self):
        # 1. AND filter that should be realtime
        filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event_multiple",
                                "negation": False,
                                "operator": "gte",
                                "event_type": "events",
                                "operator_value": 5,
                                "explicit_datetime": "-30d",
                            },
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "negation": False,
                                "event_type": "events",
                                "explicit_datetime": "-30d",
                            },
                            {"key": "$browser", "type": "person", "negation": False, "operator": "is_set"},
                        ],
                    }
                ],
            }
        }

        cohort = self._create_and_fetch("AND realtime", filters)
        self.assertEqual(cohort.cohort_type, "realtime")
        and_group = cohort.filters["properties"]["values"][0]["values"]
        # behavioral[0]
        self.assertEqual(and_group[0]["type"], "behavioral")
        self.assertEqual(
            and_group[0]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )
        self.assertEqual(and_group[0]["conditionHash"], "f9c616030a87e68f")
        # behavioral[1]
        self.assertEqual(and_group[1]["type"], "behavioral")
        self.assertEqual(
            and_group[1]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )
        self.assertEqual(and_group[1]["conditionHash"], "f9c616030a87e68f")
        # person
        self.assertEqual(and_group[2]["type"], "person")
        self.assertEqual(
            and_group[2]["bytecode"],
            ["_H", HOGQL_BYTECODE_VERSION, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12],
        )
        self.assertEqual(and_group[2]["conditionHash"], "623236814d537b73")

        # Update should keep the same inline bytecode
        cohort2 = self._patch_and_fetch(cohort.id, filters)
        self.assertEqual(cohort2.cohort_type, "realtime")
        and_group2 = cohort2.filters["properties"]["values"][0]["values"]
        self.assertEqual(
            and_group2[0]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )
        self.assertEqual(and_group2[0]["conditionHash"], "f9c616030a87e68f")

    def test_or_realtime(self):
        # 2. OR that should be realtime
        filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event_multiple",
                                "negation": False,
                                "operator": "gte",
                                "event_type": "events",
                                "operator_value": 5,
                                "explicit_datetime": "-30d",
                            },
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "negation": False,
                                "event_type": "events",
                                "explicit_datetime": "-30d",
                            },
                            {"key": "$browser", "type": "person", "negation": False, "operator": "is_set"},
                        ],
                    }
                ],
            }
        }

        cohort = self._create_and_fetch("OR realtime", filters)
        self.assertEqual(cohort.cohort_type, "realtime")
        or_group = cohort.filters["properties"]["values"][0]["values"]
        self.assertEqual(
            or_group[0]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )
        self.assertEqual(or_group[0]["conditionHash"], "f9c616030a87e68f")
        self.assertEqual(
            or_group[1]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )
        self.assertEqual(or_group[1]["conditionHash"], "f9c616030a87e68f")
        self.assertEqual(
            or_group[2]["bytecode"],
            ["_H", HOGQL_BYTECODE_VERSION, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12],
        )
        self.assertEqual(or_group[2]["conditionHash"], "623236814d537b73")

        cohort2 = self._patch_and_fetch(cohort.id, filters)
        self.assertEqual(cohort2.cohort_type, "realtime")
        or_group2 = cohort2.filters["properties"]["values"][0]["values"]
        self.assertEqual(
            or_group2[0]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )

    def test_or_not_realtime(self):
        # 3. OR that should not be realtime
        filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event_multiple",
                                "negation": False,
                                "operator": "gte",
                                "event_type": "events",
                                "operator_value": 5,
                                "explicit_datetime": "-30d",
                            }
                        ],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$groupidentify",
                                "type": "behavioral",
                                "value": "performed_event_regularly",
                                "negation": False,
                                "operator": "exact",
                                "event_type": "events",
                                "time_value": 1,
                                "min_periods": 3,
                                "time_interval": "day",
                                "total_periods": 5,
                                "operator_value": 5,
                            }
                        ],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$browser",
                                "type": "person",
                                "value": ["Chrome"],
                                "negation": False,
                                "operator": "exact",
                            }
                        ],
                    },
                ],
            }
        }

        cohort = self._create_and_fetch("OR not realtime", filters)
        self.assertIsNone(cohort.cohort_type)
        values = cohort.filters["properties"]["values"]
        # first OR group's first behavioral bytecode
        self.assertEqual(
            values[0]["values"][0]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )
        # person property bytecode
        self.assertEqual(
            values[2]["values"][0]["bytecode"],
            [
                "_H",
                HOGQL_BYTECODE_VERSION,
                32,
                "Chrome",
                32,
                "$browser",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                11,
            ],
        )

        cohort2 = self._patch_and_fetch(cohort.id, filters)
        self.assertIsNone(cohort2.cohort_type)
        values2 = cohort2.filters["properties"]["values"]
        self.assertEqual(
            values2[0]["values"][0]["bytecode"], ["_H", HOGQL_BYTECODE_VERSION, 32, "$pageview", 32, "event", 1, 1, 11]
        )

    def test_event_properties_realtime(self):
        # 4. with event properties should be realtime
        filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event_multiple",
                                "negation": False,
                                "operator": "gte",
                                "event_type": "events",
                                "event_filters": [
                                    {
                                        "key": "$active_feature_flags",
                                        "type": "event",
                                        "value": "is_set",
                                        "operator": "is_set",
                                    },
                                    {
                                        "key": "$feature/active-hours-heatmap",
                                        "type": "event",
                                        "value": "is_set",
                                        "operator": "is_set",
                                    },
                                    {"key": "text", "type": "element", "value": "is_set", "operator": "is_set"},
                                ],
                                "operator_value": 5,
                                "explicit_datetime": "-30d",
                            }
                        ],
                    }
                ],
            }
        }

        cohort = self._create_and_fetch("Event props realtime", filters)
        self.assertEqual(cohort.cohort_type, "realtime")
        node = cohort.filters["properties"]["values"][0]["values"][0]
        self.assertEqual(node["type"], "behavioral")
        self.assertEqual(
            node["bytecode"],
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
                31,
                32,
                "$active_feature_flags",
                32,
                "properties",
                1,
                2,
                12,
                31,
                32,
                "$feature/active-hours-heatmap",
                32,
                "properties",
                1,
                2,
                12,
                52,
                "lambda",
                1,
                0,
                5,
                31,
                36,
                0,
                12,
                38,
                53,
                0,
                32,
                "elements_chain_texts",
                1,
                1,
                2,
                "arrayExists",
                2,
                3,
                3,
                3,
                2,
            ],
        )
        self.assertEqual(node["conditionHash"], "827d18e80726ed84")

        cohort2 = self._patch_and_fetch(cohort.id, filters)
        self.assertEqual(cohort2.cohort_type, "realtime")
        node2 = cohort2.filters["properties"]["values"][0]["values"][0]
        self.assertEqual(node2["conditionHash"], "827d18e80726ed84")
