import os
import json
import tempfile

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.management.commands.survey_cohort_bytecode_stl import (
    aggregate_survey,
    iter_bytecode_leaves,
    iter_instructions,
)
from posthog.models.cohort.cohort import Cohort, CohortType

from common.hogvm.python.operation import Operation

# Opcode values used to hand-build synthetic bytecode (mirror common/hogvm/python/operation.py).
GET_GLOBAL, CALL_GLOBAL, AND, PLUS = 1, 2, 3, 6
GT, IN_COHORT = 13, 27
TRUE, NULL, STRING, INTEGER, RETURN = 29, 31, 32, 33, 38


class TestBytecodeWalker(BaseTest):
    @parameterized.expand(
        [
            (
                "string_then_return",
                ["_H", 1, STRING, "hello", RETURN],
                [(Operation.STRING, ["hello"]), (Operation.RETURN, [])],
            ),
            (
                "integer_plus",
                ["_H", 1, INTEGER, 2, INTEGER, 1, PLUS, RETURN],
                [
                    (Operation.INTEGER, [2]),
                    (Operation.INTEGER, [1]),
                    (Operation.PLUS, []),
                    (Operation.RETURN, []),
                ],
            ),
            (
                "call_global_is_null",
                ["_H", 1, NULL, CALL_GLOBAL, "isNull", 1, RETURN],
                [
                    (Operation.NULL, []),
                    (Operation.CALL_GLOBAL, ["isNull", 1]),
                    (Operation.RETURN, []),
                ],
            ),
            (
                "get_global_chain",
                ["_H", 1, STRING, "x", GET_GLOBAL, 1, RETURN],
                [
                    (Operation.STRING, ["x"]),
                    (Operation.GET_GLOBAL, [1]),
                    (Operation.RETURN, []),
                ],
            ),
            (
                "and_with_count_operand",
                ["_H", 1, TRUE, TRUE, AND, 2, RETURN],
                [
                    (Operation.TRUE, []),
                    (Operation.TRUE, []),
                    (Operation.AND, [2]),
                    (Operation.RETURN, []),
                ],
            ),
            (
                "v0_header_single_slot_skip",
                ["_h", TRUE, RETURN],
                [(Operation.TRUE, []), (Operation.RETURN, [])],
            ),
        ]
    )
    def test_iter_instructions_disassembles(self, _name, bytecode, expected):
        self.assertEqual(list(iter_instructions(bytecode)), expected)

    @parameterized.expand(
        [
            ("truncated_operand", ["_H", 1, STRING], "truncated operands for STRING"),
            ("unknown_opcode", ["_H", 1, 9999], "unknown opcode 9999"),
        ]
    )
    def test_iter_instructions_raises_on_malformed(self, _name, bytecode, expected_msg):
        with self.assertRaises(ValueError) as ctx:
            list(iter_instructions(bytecode))
        self.assertIn(expected_msg, str(ctx.exception))

    def test_iter_bytecode_leaves_walks_and_or_tree(self):
        properties = {
            "type": "AND",
            "values": [
                {"type": "person", "conditionHash": "h1", "bytecode": ["_H", 1, TRUE, RETURN]},
                {
                    "type": "OR",
                    "values": [
                        {"type": "behavioral", "conditionHash": "h2", "bytecode": ["_H", 1, TRUE, RETURN]},
                        {"type": "person", "conditionHash": "h3"},  # no bytecode -> skipped
                    ],
                },
            ],
        }
        leaves = list(iter_bytecode_leaves(properties))
        self.assertEqual([leaf["conditionHash"] for leaf in leaves], ["h1", "h2"])


class TestAggregateSurvey(BaseTest):
    def test_aggregates_histograms_and_rust_gaps(self):
        rows = [
            # isNull: supported native.
            (
                1,
                2,
                {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "person",
                                "conditionHash": "h1",
                                "bytecode": ["_H", 1, NULL, CALL_GLOBAL, "isNull", 1, RETURN],
                            },
                        ],
                    }
                },
            ),
            # inCohort: CALL_GLOBAL name missing from the Rust STL.
            (
                2,
                2,
                {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "cohort",
                                "conditionHash": "h2",
                                "bytecode": ["_H", 1, STRING, "x", CALL_GLOBAL, "inCohort", 1, RETURN],
                            },
                        ],
                    }
                },
            ),
            # IN_COHORT: opcode the Rust VM returns NotImplemented for.
            (
                3,
                7,
                {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "cohort",
                                "conditionHash": "h3",
                                "bytecode": ["_H", 1, INTEGER, 5, IN_COHORT, RETURN],
                            },
                        ],
                    }
                },
            ),
            # sortableSemver: present in Rust hog_stl but transitively needs empty/splitByString/toInt.
            (
                4,
                7,
                {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "person",
                                "conditionHash": "h4",
                                "bytecode": ["_H", 1, STRING, "1.2.3", CALL_GLOBAL, "sortableSemver", 1, RETURN],
                            },
                        ],
                    }
                },
            ),
            # Truncated bytecode -> recorded as a walk failure, does not crash the survey.
            (
                5,
                7,
                {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"type": "person", "conditionHash": "h5", "bytecode": ["_H", 1, STRING]},
                        ],
                    }
                },
            ),
        ]

        result = aggregate_survey(rows)

        totals = result["totals"]
        self.assertEqual(totals["cohorts_scanned"], 5)
        self.assertEqual(totals["teams_scanned"], 2)
        self.assertEqual(totals["leaves_with_bytecode"], 5)
        self.assertEqual(totals["leaves_walked_ok"], 4)
        self.assertEqual(totals["leaves_walk_failed"], 1)
        self.assertEqual(totals["unique_condition_hashes"], 5)

        stl_by_name = {entry["name"]: entry for entry in result["stl_functions"]}
        self.assertTrue(stl_by_name["isNull"]["in_rust_stl"])
        self.assertFalse(stl_by_name["inCohort"]["in_rust_stl"])
        self.assertTrue(stl_by_name["sortableSemver"]["in_rust_stl"])
        self.assertEqual(stl_by_name["isNull"]["distinct_cohorts"], 1)

        gaps = result["rust_gaps"]
        self.assertEqual(gaps["missing_stl_natives"], ["inCohort"])
        self.assertEqual(gaps["sortable_semver_transitive_deps"], ["empty", "splitByString", "toInt"])
        self.assertEqual(gaps["not_implemented_opcodes_used"], ["IN_COHORT"])

        self.assertEqual(len(result["walk_failures"]), 1)
        self.assertEqual(result["walk_failures"][0]["cohort_id"], 5)

    def test_real_compiler_bytecode_is_walked_and_isnull_is_supported(self):
        # Compile a real person-property numeric comparison; it wraps the GT in isNull guards.
        from posthog.api.cohort import generate_cohort_filter_bytecode

        bytecode, error, condition_hash = generate_cohort_filter_bytecode(
            {"key": "age", "type": "person", "value": 13, "operator": "gt"}, self.team
        )
        self.assertIsNone(error)
        assert bytecode is not None  # narrow for mypy

        row = (
            101,
            self.team.id,
            {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "conditionHash": condition_hash, "bytecode": bytecode},
                    ],
                }
            },
        )
        result = aggregate_survey([row])

        self.assertEqual(result["totals"]["leaves_walked_ok"], 1)
        self.assertEqual(result["totals"]["leaves_walk_failed"], 0)

        stl_names = {entry["name"] for entry in result["stl_functions"]}
        self.assertIn("isNull", stl_names)
        opcode_names = {entry["opcode"] for entry in result["opcodes"]}
        self.assertIn("GT", opcode_names)  # the actual comparison survives disassembly

        # isNull is now a supported native (M8.a), and a person-property comparison needs nothing else.
        self.assertEqual(result["rust_gaps"]["missing_stl_natives"], [])
        self.assertEqual(result["rust_gaps"]["not_implemented_opcodes_used"], [])


class TestSurveyCommand(BaseTest):
    def test_command_writes_survey_json_for_realtime_cohorts(self):
        from posthog.api.cohort import generate_cohort_filter_bytecode

        bytecode, _error, condition_hash = generate_cohort_filter_bytecode(
            {"key": "age", "type": "person", "value": 13, "operator": "gt"}, self.team
        )
        Cohort.objects.create(
            team=self.team,
            name="survey-test-realtime",
            cohort_type=CohortType.REALTIME,
            deleted=False,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "person",
                            "key": "age",
                            "value": 13,
                            "operator": "gt",
                            "conditionHash": condition_hash,
                            "bytecode": bytecode,
                        },
                    ],
                }
            },
        )

        output_path = os.path.join(tempfile.mkdtemp(), "survey.json")
        call_command("survey_cohort_bytecode_stl", "--team-id", str(self.team.id), "--output", output_path)

        with open(output_path) as f:
            result = json.load(f)

        self.assertEqual(result["totals"]["cohorts_scanned"], 1)
        self.assertEqual(result["totals"]["leaves_walked_ok"], 1)
        self.assertIn("isNull", {entry["name"] for entry in result["stl_functions"]})
        self.assertEqual(result["rust_gaps"]["missing_stl_natives"], [])
        self.assertEqual(result["scope"]["team_id"], self.team.id)
