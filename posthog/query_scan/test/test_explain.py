import json
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.explain import parse_query_plan

FIXTURES = Path(__file__).parent / "fixtures"


def load_plan(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def events_read_node(condition: str, keys: list[str], *, selected_granules: int = 1000) -> dict[str, object]:
    return {
        "Node Type": "ReadFromMergeTree",
        "Description": "posthog.sharded_events",
        "Indexes": [
            {
                "Type": "Min-Max",
                "Keys": keys,
                "Condition": condition,
                "Initial Granules": 1000,
                "Selected Granules": selected_granules,
            }
        ],
    }


def min_max_read(condition: str, keys: list[str]) -> list[dict[str, object]]:
    return [{"Plan": events_read_node(condition, keys)}]


class TestExplainParsing(SimpleTestCase):
    @parameterized.expand(
        [
            # fixture, primary key columns, event in the key, granules after the last step, the
            # lower unix bound the Min-Max step could apply
            ("plan_event_filter_used", ("team_id", "toDate(timestamp)", "event"), True, 8567, 1788461182),
            ("plan_no_event_filter", ("team_id", "toDate(timestamp)"), False, 329267, 1788461215),
            ("plan_no_date_bound", ("team_id", "event"), True, 412056, None),
            (
                "plan_event_filter_in_or",
                ("team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)"),
                True,
                23018,
                1788461220,
            ),
            ("plan_skip_index_pruned", ("team_id", "toDate(timestamp)"), False, 103415, 1788461227),
        ]
    )
    def test_events_read_reports_table_keys_granules_and_bounds(
        self,
        fixture: str,
        expected_keys: tuple[str, ...],
        event_in_key: bool,
        final_granules: int,
        lower_bound: int | None,
    ) -> None:
        plan = parse_query_plan(load_plan(fixture))

        read = plan.heaviest_events_read()
        assert read is not None
        self.assertEqual(read.table, "posthog.sharded_events")
        primary_key = read.primary_key()
        assert primary_key is not None
        self.assertEqual(primary_key.keys, expected_keys)
        self.assertEqual("event" in primary_key.keys, event_in_key)
        self.assertEqual(read.selected_granules(), final_granules)
        bounds = read.timestamp_bounds()
        self.assertEqual(bounds.lower, lower_bound)
        self.assertIsNone(bounds.upper)

    def test_steps_are_kept_in_plan_order(self) -> None:
        read = parse_query_plan(load_plan("plan_skip_index_pruned")).heaviest_events_read()
        assert read is not None

        self.assertEqual([step.type for step in read.indexes], ["Min-Max", "Partition", "PrimaryKey", "Skip", "Skip"])
        self.assertEqual(len(read.skip_steps()), 2)

    @parameterized.expand(
        [
            ("lower bound only", "(timestamp in [1700000000, +Inf))", ["timestamp"], 1700000000, None),
            ("upper bound only", "(timestamp in (-Inf, 1800000000])", ["timestamp"], None, 1800000000),
            # ClickHouse prints a range with a start and an end as two clauses, the end first, so a
            # parser that stopped at the first clause would report every bounded query as unbounded.
            (
                "both bounds, as ClickHouse prints them",
                "and((timestamp in (-Inf, 1800000000]), (timestamp in [1700000000, +Inf)))",
                ["timestamp"],
                1700000000,
                1800000000,
            ),
            ("no timestamp key", "true", [], None, None),
        ]
    )
    def test_timestamp_bounds_parse_the_canonical_forms(
        self, _name: str, condition: str, keys: list[str], lower: int | None, upper: int | None
    ) -> None:
        read = parse_query_plan(min_max_read(condition, keys)).heaviest_events_read()
        assert read is not None

        bounds = read.timestamp_bounds()
        self.assertEqual(bounds.lower, lower)
        self.assertEqual(bounds.upper, upper)

    def test_the_largest_of_several_events_reads_is_the_one_judged(self) -> None:
        # A join or a union reads the events table more than once, and the read that kept the most
        # granules is the one that made the query slow, whatever order ClickHouse lists them in.
        plan = parse_query_plan(
            [
                {
                    "Plan": {
                        "Node Type": "Join",
                        "Plans": [
                            events_read_node("(timestamp in [1700000000, +Inf))", ["timestamp"], selected_granules=10),
                            events_read_node("true", [], selected_granules=5000),
                        ],
                    }
                }
            ]
        )

        heaviest = plan.heaviest_events_read()
        assert heaviest is not None
        self.assertEqual(heaviest.selected_granules(), 5000)
        self.assertEqual(len(plan.events_reads()), 2)

    def test_persons_join_plan_names_both_reads(self) -> None:
        plan = parse_query_plan(load_plan("plan_persons_join"))

        events_read = plan.heaviest_events_read()
        assert events_read is not None
        self.assertEqual(events_read.table, "posthog.sharded_events")
        self.assertEqual([read.table for read in plan.person_reads()], ["posthog.person"])

    @parameterized.expand(
        [
            ("object storage read has no events read", "plan_object_storage_read"),
            ("a replay list reads its own table, not events", "plan_replay_list_in_subqueries"),
        ]
    )
    def test_plans_without_an_events_read(self, _name: str, fixture: str) -> None:
        plan = parse_query_plan(load_plan(fixture))

        self.assertIsNone(plan.heaviest_events_read())

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
        self.assertIsNone(plan.heaviest_events_read())

    def test_json_text_is_accepted(self) -> None:
        raw = (FIXTURES / "plan_event_filter_used.json").read_text()

        read = parse_query_plan(raw).heaviest_events_read()
        assert read is not None
        self.assertEqual(read.table, "posthog.sharded_events")
