import json
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.explain import parse_query_plan

FIXTURES = Path(__file__).parent / "fixtures"


def load_plan(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def plan_read(keys: list[str], selected_granules: int) -> dict[str, object]:
    return {
        "Node Type": "ReadFromMergeTree",
        "Description": "posthog.sharded_events",
        "Indexes": [
            {
                "Type": "PrimaryKey",
                "Keys": keys,
                "Initial Granules": 60000,
                "Selected Granules": selected_granules,
            }
        ],
    }


# Two events reads where only the first pruned on `event`. Built here rather than as a fixture,
# because what matters is the disagreement between the reads, not the shape of real EXPLAIN output.
MIXED_PRUNING_PLAN = parse_query_plan(
    [
        {
            "Plan": {
                "Node Type": "Union",
                "Plans": [
                    {"Plan": plan_read(["team_id", "toDate(timestamp)", "event"], 800)},
                    {"Plan": plan_read(["team_id", "toDate(timestamp)"], 40000)},
                ],
            }
        }
    ]
)


class TestExplainParsing(SimpleTestCase):
    @parameterized.expand(
        [
            ("event_filter_usable", True, ("team_id", "toDate(timestamp)", "event")),
            ("no_event_filter", False, ("team_id", "toDate(timestamp)")),
        ]
    )
    def test_events_read_reports_primary_key_use(
        self, fixture: str, expected_key_used: bool, expected_keys: tuple[str, ...]
    ) -> None:
        plan = parse_query_plan(load_plan(fixture))

        events_reads = plan.events_reads()
        self.assertEqual(len(events_reads), 1)
        self.assertEqual(events_reads[0].description, "posthog.sharded_events")
        primary_key = events_reads[0].primary_key()
        assert primary_key is not None
        self.assertEqual(primary_key.keys, expected_keys)
        self.assertEqual(plan.event_key_used(), expected_key_used)

    @parameterized.expand(
        [
            ("the events table with no database qualifier", "events", True),
            ("the native-JSON table", "posthog.sharded_events_json", True),
            ("another table whose name ends in events", "posthog.ai_events", False),
        ]
    )
    def test_which_table_names_count_as_the_events_read(
        self, _name: str, description: str, expected_events_read: bool
    ) -> None:
        plan = parse_query_plan(
            [
                {
                    "Plan": {
                        "Node Type": "ReadFromMergeTree",
                        "Description": description,
                        "Indexes": [{"Type": "PrimaryKey", "Keys": ["team_id", "toDate(timestamp)", "event"]}],
                    }
                }
            ]
        )

        self.assertEqual(bool(plan.events_reads()), expected_events_read)
        self.assertEqual(plan.event_key_used(), True if expected_events_read else None)

    @parameterized.expand(
        [
            ("nothing at all", None),
            ("unparseable text", "not json at all"),
            ("a read without a description", [{"Plan": {"Node Type": "ReadFromMergeTree", "Indexes": []}}]),
        ]
    )
    def test_unexpected_shape_reports_no_events_read(self, _name: str, payload: object) -> None:
        plan = parse_query_plan(payload)

        self.assertEqual(plan.reads, ())
        self.assertIsNone(plan.event_key_used())

    def test_json_text_is_accepted(self) -> None:
        raw = (FIXTURES / "event_filter_usable.json").read_text()

        self.assertTrue(parse_query_plan(raw).event_key_used())
