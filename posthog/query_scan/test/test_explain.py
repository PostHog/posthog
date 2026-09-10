import json
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.explain import parse_query_plan

FIXTURES = Path(__file__).parent / "fixtures"


def load_plan(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def min_max_read(condition: str, keys: list[str]) -> list[dict[str, object]]:
    return [
        {
            "Plan": {
                "Node Type": "ReadFromMergeTree",
                "Description": "posthog.sharded_events",
                "Indexes": [
                    {
                        "Type": "Min-Max",
                        "Keys": keys,
                        "Condition": condition,
                        "Initial Granules": 1000,
                        "Selected Granules": 1000,
                    }
                ],
            }
        }
    ]


class TestExplainParsing(SimpleTestCase):
    @parameterized.expand(
        [
            # fixture, primary key columns, event in the key, granules after the last step, has a
            # timestamp key, the lower unix bound the Min-Max step could apply
            ("plan_event_filter_used", ("team_id", "toDate(timestamp)", "event"), True, 8567, True, 1788461182),
            ("plan_no_event_filter", ("team_id", "toDate(timestamp)"), False, 329267, True, 1788461215),
            ("plan_no_date_bound", ("team_id", "event"), True, 412056, False, None),
            (
                "plan_event_filter_in_or",
                ("team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)"),
                True,
                23018,
                True,
                1788461220,
            ),
            ("plan_skip_index_pruned", ("team_id", "toDate(timestamp)"), False, 103415, True, 1788461227),
            ("event_filter_usable", ("team_id", "toDate(timestamp)", "event"), True, 750, True, 1700000000),
            ("no_event_filter", ("team_id", "toDate(timestamp)"), False, 39000, True, 1700000000),
        ]
    )
    def test_events_read_reports_table_keys_granules_and_bounds(
        self,
        fixture: str,
        expected_keys: tuple[str, ...],
        event_in_key: bool,
        final_granules: int,
        has_timestamp_key: bool,
        lower_bound: int | None,
    ) -> None:
        plan = parse_query_plan(load_plan(fixture))

        read = plan.events_read()
        assert read is not None
        self.assertEqual(read.table, "posthog.sharded_events")
        primary_key = read.primary_key()
        assert primary_key is not None
        self.assertEqual(primary_key.keys, expected_keys)
        self.assertEqual("event" in primary_key.keys, event_in_key)
        self.assertEqual(read.selected_granules(), final_granules)
        self.assertEqual(read.has_timestamp_key(), has_timestamp_key)
        bounds = read.timestamp_bounds()
        self.assertEqual(bounds.lower, lower_bound)
        self.assertIsNone(bounds.upper)

    def test_steps_are_kept_in_order_and_skip_steps_carry_names(self) -> None:
        read = parse_query_plan(load_plan("plan_skip_index_pruned")).events_read()
        assert read is not None

        self.assertEqual([step.type for step in read.indexes], ["Min-Max", "Partition", "PrimaryKey", "Skip", "Skip"])
        self.assertEqual(
            [step.name for step in read.skip_steps()],
            ["minmax_$session_id", "minmax_sharded_events_timestamp"],
        )

    @parameterized.expand(
        [
            ("lower bound only", "(timestamp in [1700000000, +Inf))", ["timestamp"], 1700000000, None),
            ("upper bound only", "(timestamp in (-Inf, 1800000000])", ["timestamp"], None, 1800000000),
            ("both bounds", "(timestamp in [1700000000, 1800000000])", ["timestamp"], 1700000000, 1800000000),
            ("no timestamp key", "true", [], None, None),
        ]
    )
    def test_timestamp_bounds_parse_the_canonical_forms(
        self, _name: str, condition: str, keys: list[str], lower: int | None, upper: int | None
    ) -> None:
        read = parse_query_plan(min_max_read(condition, keys)).events_read()
        assert read is not None

        bounds = read.timestamp_bounds()
        self.assertEqual(bounds.lower, lower)
        self.assertEqual(bounds.upper, upper)

    def test_persons_join_plan_names_both_reads(self) -> None:
        plan = parse_query_plan(load_plan("plan_persons_join"))

        events_read = plan.events_read()
        assert events_read is not None
        self.assertEqual(events_read.table, "posthog.sharded_events")
        self.assertEqual([read.table for read in plan.person_reads()], ["posthog.person"])
        self.assertFalse(plan.has_non_mergetree_read)

    @parameterized.expand(
        [
            ("object storage read has no events read", "plan_object_storage_read", True),
            ("a replay list reads its own table, not events", "plan_replay_list_in_subqueries", False),
        ]
    )
    def test_plans_without_an_events_read(self, _name: str, fixture: str, non_mergetree: bool) -> None:
        plan = parse_query_plan(load_plan(fixture))

        self.assertIsNone(plan.events_read())
        self.assertEqual(plan.has_non_mergetree_read, non_mergetree)

    @parameterized.expand(
        [
            ("the events table with no database qualifier", "events", True, False),
            ("the native-JSON table", "posthog.sharded_events_json", True, False),
            ("another table whose name ends in events", "posthog.ai_events", False, False),
            ("the persons table", "posthog.person", False, True),
            ("a person override table", "posthog.person_distinct_id_overrides", False, True),
        ]
    )
    def test_table_names_are_classified_by_the_description(
        self, _name: str, description: str, reads_events: bool, reads_persons: bool
    ) -> None:
        plan = parse_query_plan(
            [{"Plan": {"Node Type": "ReadFromMergeTree", "Description": description, "Indexes": []}}]
        )

        read = plan.reads[0]
        self.assertEqual(read.reads_events(), reads_events)
        self.assertEqual(read.reads_persons(), reads_persons)

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
        self.assertIsNone(plan.events_read())

    def test_json_text_is_accepted(self) -> None:
        raw = (FIXTURES / "plan_event_filter_used.json").read_text()

        read = parse_query_plan(raw).events_read()
        assert read is not None
        self.assertEqual(read.table, "posthog.sharded_events")
