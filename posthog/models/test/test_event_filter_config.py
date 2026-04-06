from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.event_filter_config import (
    MAX_CONDITIONS,
    MAX_TREE_DEPTH,
    EventFilterConfig,
    EventFilterMode,
    evaluate_filter_tree,
    prune_filter_tree,
    run_test_cases,
    tree_has_conditions,
    validate_filter_tree,
    validate_test_cases,
)


def _cond(field: str = "event_name", operator: str = "exact", value: str = "pageview") -> dict:
    return {"type": "condition", "field": field, "operator": operator, "value": value}


def _and(*children: dict) -> dict:
    return {"type": "and", "children": list(children)}


def _or(*children: dict) -> dict:
    return {"type": "or", "children": list(children)}


def _not(child: dict) -> dict:
    return {"type": "not", "child": child}


class TestValidateFilterTree(SimpleTestCase):
    @parameterized.expand(
        [
            ("simple_condition", _cond()),
            ("and_two_conditions", _and(_cond(), _cond(field="distinct_id", value="user1"))),
            ("or_two_conditions", _or(_cond(), _cond(operator="contains", value="view"))),
            ("not_condition", _not(_cond())),
            ("nested_and_or", _and(_or(_cond(), _cond(value="click")), _cond(field="distinct_id", value="u"))),
        ]
    )
    def test_valid_trees(self, _name: str, tree: dict):
        validate_filter_tree(tree)

    @parameterized.expand(
        [
            ("not_a_dict", "string", "must be an object"),
            ("list_node", [1, 2], "must be an object"),
            ("invalid_type", {"type": "xor"}, "type must be one of"),
            ("missing_type", {}, "type must be one of"),
        ]
    )
    def test_invalid_node_type(self, _name: str, tree: object, expected_msg: str):
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree(tree)
        self.assertIn(expected_msg, str(ctx.exception))

    def test_exceeds_max_conditions(self):
        tree = _and(*[_cond(value=str(i)) for i in range(MAX_CONDITIONS + 1)])
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree(tree)
        self.assertIn("maximum", str(ctx.exception))

    def test_exactly_max_conditions_is_valid(self):
        tree = _and(*[_cond(value=str(i)) for i in range(MAX_CONDITIONS)])
        validate_filter_tree(tree)

    def test_exceeds_max_depth(self):
        node: dict = _cond()
        for _ in range(MAX_TREE_DEPTH + 1):
            node = _not(node)
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree(node)
        self.assertIn("depth", str(ctx.exception))

    def test_exactly_max_depth_is_valid(self):
        node: dict = _cond()
        for _ in range(MAX_TREE_DEPTH):
            node = _not(node)
        validate_filter_tree(node)


class TestValidateCondition(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_field", {"type": "condition", "operator": "exact", "value": "x"}, "missing required key 'field'"),
            (
                "missing_operator",
                {"type": "condition", "field": "event_name", "value": "x"},
                "missing required key 'operator'",
            ),
            (
                "missing_value",
                {"type": "condition", "field": "event_name", "operator": "exact"},
                "missing required key 'value'",
            ),
            (
                "invalid_field",
                {"type": "condition", "field": "bad_field", "operator": "exact", "value": "x"},
                "field must be one of",
            ),
            (
                "invalid_operator",
                {"type": "condition", "field": "event_name", "operator": "regex", "value": "x"},
                "operator must be one of",
            ),
            (
                "empty_value",
                {"type": "condition", "field": "event_name", "operator": "exact", "value": ""},
                "value must be a non-empty string",
            ),
            (
                "non_string_value",
                {"type": "condition", "field": "event_name", "operator": "exact", "value": 123},
                "value must be a non-empty string",
            ),
        ]
    )
    def test_invalid_conditions(self, _name: str, tree: dict, expected_msg: str):
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree(tree)
        self.assertIn(expected_msg, str(ctx.exception))


class TestValidateNodeStructure(SimpleTestCase):
    def test_not_missing_child(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree({"type": "not"})
        self.assertIn("must have a 'child'", str(ctx.exception))

    def test_and_children_not_list(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree({"type": "and", "children": "not_a_list"})
        self.assertIn("must have a 'children' list", str(ctx.exception))

    def test_or_children_not_list(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree({"type": "or", "children": "not_a_list"})
        self.assertIn("must have a 'children' list", str(ctx.exception))

    def test_nested_invalid_child(self):
        tree = _and(_cond(), {"type": "condition", "field": "bad", "operator": "exact", "value": "x"})
        with self.assertRaises(ValidationError) as ctx:
            validate_filter_tree(tree)
        self.assertIn("children[1]", str(ctx.exception))


class TestPruneFilterTree(SimpleTestCase):
    def test_removes_empty_group(self):
        self.assertIsNone(prune_filter_tree({"type": "and", "children": []}))

    def test_collapses_single_child_group(self):
        cond = _cond()
        self.assertEqual(prune_filter_tree(_and(cond)), cond)

    def test_removes_not_with_empty_child(self):
        self.assertIsNone(prune_filter_tree(_not({"type": "or", "children": []})))

    def test_preserves_valid_tree(self):
        tree = _and(_cond(), _cond(value="click"))
        self.assertEqual(prune_filter_tree(tree), tree)

    def test_collapses_nested_single_child_groups(self):
        cond = _cond()
        tree = _or(_and(cond))
        self.assertEqual(prune_filter_tree(tree), cond)


class TestEvaluateFilterTree(SimpleTestCase):
    @parameterized.expand(
        [
            ("exact_match", _cond("event_name", "exact", "pageview"), {"event_name": "pageview"}, True),
            ("exact_no_match", _cond("event_name", "exact", "pageview"), {"event_name": "click"}, False),
            ("contains_match", _cond("event_name", "contains", "view"), {"event_name": "pageview"}, True),
            ("contains_no_match", _cond("event_name", "contains", "click"), {"event_name": "pageview"}, False),
            ("missing_field", _cond("event_name", "exact", "pageview"), {}, False),
            ("distinct_id_match", _cond("distinct_id", "exact", "u1"), {"distinct_id": "u1"}, True),
        ]
    )
    def test_condition(self, _name: str, tree: dict, event: dict, expected: bool):
        self.assertEqual(evaluate_filter_tree(tree, event), expected)

    def test_and_all_true(self):
        tree = _and(_cond("event_name", "exact", "pageview"), _cond("distinct_id", "exact", "u1"))
        self.assertTrue(evaluate_filter_tree(tree, {"event_name": "pageview", "distinct_id": "u1"}))

    def test_and_one_false(self):
        tree = _and(_cond("event_name", "exact", "pageview"), _cond("distinct_id", "exact", "u1"))
        self.assertFalse(evaluate_filter_tree(tree, {"event_name": "pageview", "distinct_id": "u2"}))

    def test_and_empty_children_returns_false(self):
        self.assertFalse(evaluate_filter_tree({"type": "and", "children": []}, {}))

    def test_or_one_true(self):
        tree = _or(_cond("event_name", "exact", "pageview"), _cond("event_name", "exact", "click"))
        self.assertTrue(evaluate_filter_tree(tree, {"event_name": "click"}))

    def test_or_none_true(self):
        tree = _or(_cond("event_name", "exact", "pageview"), _cond("event_name", "exact", "click"))
        self.assertFalse(evaluate_filter_tree(tree, {"event_name": "submit"}))

    def test_not_inverts(self):
        self.assertFalse(
            evaluate_filter_tree(_not(_cond("event_name", "exact", "pageview")), {"event_name": "pageview"})
        )
        self.assertTrue(evaluate_filter_tree(_not(_cond("event_name", "exact", "pageview")), {"event_name": "click"}))


class TestTreeHasConditions(SimpleTestCase):
    @parameterized.expand(
        [
            ("bare_condition", _cond(), True),
            ("nested_condition", _and(_cond()), True),
            ("not_condition", _not(_cond()), True),
            ("empty_and", {"type": "and", "children": []}, False),
            ("empty_or", {"type": "or", "children": []}, False),
            ("not_a_dict", "string", False),
            ("not_with_empty_child", _not({"type": "or", "children": []}), False),
        ]
    )
    def test_tree_has_conditions(self, _name: str, tree: object, expected: bool):
        self.assertEqual(tree_has_conditions(tree), expected)


class TestValidateTestCases(SimpleTestCase):
    def test_valid_test_case(self):
        validate_test_cases([{"event_name": "pageview", "expected_result": "drop"}])

    def test_not_a_list(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_test_cases("not_a_list")
        self.assertIn("Must be a list", str(ctx.exception))

    def test_entry_not_a_dict(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_test_cases(["not_a_dict"])
        self.assertIn("must be an object", str(ctx.exception))

    def test_missing_expected_result(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_test_cases([{"event_name": "pageview"}])
        self.assertIn("missing 'expected_result'", str(ctx.exception))

    def test_invalid_expected_result(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_test_cases([{"expected_result": "maybe"}])
        self.assertIn("must be 'drop' or 'ingest'", str(ctx.exception))

    def test_non_string_field(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_test_cases([{"event_name": 123, "expected_result": "drop"}])
        self.assertIn("must be a string", str(ctx.exception))


class TestRunTestCases(SimpleTestCase):
    def test_passing_test_cases(self):
        tree = _cond("event_name", "exact", "pageview")
        test_cases = [
            {"event_name": "pageview", "expected_result": "drop"},
            {"event_name": "click", "expected_result": "ingest"},
        ]
        run_test_cases(tree, test_cases)

    def test_failing_test_case_expected_drop(self):
        tree = _cond("event_name", "exact", "pageview")
        test_cases = [{"event_name": "click", "expected_result": "drop"}]
        with self.assertRaises(ValidationError) as ctx:
            run_test_cases(tree, test_cases)
        self.assertIn("expected 'drop' but got 'ingest'", str(ctx.exception))

    def test_failing_test_case_expected_ingest(self):
        tree = _cond("event_name", "exact", "pageview")
        test_cases = [{"event_name": "pageview", "expected_result": "ingest"}]
        with self.assertRaises(ValidationError) as ctx:
            run_test_cases(tree, test_cases)
        self.assertIn("expected 'ingest' but got 'drop'", str(ctx.exception))

    def test_multiple_failures_reported(self):
        tree = _cond("event_name", "exact", "pageview")
        test_cases = [
            {"event_name": "click", "expected_result": "drop"},
            {"event_name": "pageview", "expected_result": "ingest"},
        ]
        with self.assertRaises(ValidationError) as ctx:
            run_test_cases(tree, test_cases)
        msg = str(ctx.exception)
        self.assertIn("Test case 0", msg)
        self.assertIn("Test case 1", msg)

    def test_test_case_with_distinct_id(self):
        tree = _and(_cond("event_name", "exact", "pageview"), _cond("distinct_id", "contains", "bot"))
        test_cases = [
            {"event_name": "pageview", "distinct_id": "bot-123", "expected_result": "drop"},
            {"event_name": "pageview", "distinct_id": "user-1", "expected_result": "ingest"},
        ]
        run_test_cases(tree, test_cases)

    def test_complex_tree_with_many_test_cases(self):
        # Drop if: (event is "$autocapture" OR event contains "bot_")
        #          AND NOT (distinct_id is "admin-user")
        tree = _and(
            _or(
                _cond("event_name", "exact", "$autocapture"),
                _cond("event_name", "contains", "bot_"),
            ),
            _not(_cond("distinct_id", "exact", "admin-user")),
        )
        test_cases = [
            # $autocapture from regular user -> drop
            {"event_name": "$autocapture", "distinct_id": "user-1", "expected_result": "drop"},
            # bot_ prefixed event from regular user -> drop
            {"event_name": "bot_heartbeat", "distinct_id": "user-2", "expected_result": "drop"},
            # $autocapture from admin -> NOT negated, so ingest
            {"event_name": "$autocapture", "distinct_id": "admin-user", "expected_result": "ingest"},
            # bot_ event from admin -> also protected
            {"event_name": "bot_ping", "distinct_id": "admin-user", "expected_result": "ingest"},
            # normal event from regular user -> doesn't match OR branch, ingest
            {"event_name": "purchase", "distinct_id": "user-1", "expected_result": "ingest"},
            # normal event from admin -> ingest
            {"event_name": "login", "distinct_id": "admin-user", "expected_result": "ingest"},
            # partial match on "bot_" via contains -> drop
            {"event_name": "internal_bot_check", "distinct_id": "service-1", "expected_result": "drop"},
            # event_name missing -> condition returns false, ingest
            {"distinct_id": "user-1", "expected_result": "ingest"},
            # distinct_id missing -> NOT(false)=true, OR still needs to match
            {"event_name": "$autocapture", "expected_result": "drop"},
        ]
        run_test_cases(tree, test_cases)


class TestEventFilterConfigModel(BaseTest):
    def test_create_and_retrieve(self):
        tree = _and(_cond("event_name", "exact", "pageview"), _cond("distinct_id", "contains", "bot"))
        test_cases = [
            {"event_name": "pageview", "distinct_id": "bot-123", "expected_result": "drop"},
            {"event_name": "pageview", "distinct_id": "user-1", "expected_result": "ingest"},
        ]
        config = EventFilterConfig.objects.create(
            team=self.team,
            mode=EventFilterMode.DRY_RUN,
            filter_tree=tree,
            test_cases=test_cases,
        )

        retrieved = EventFilterConfig.objects.get(pk=config.pk)
        self.assertEqual(retrieved.team_id, self.team.id)
        self.assertEqual(retrieved.mode, EventFilterMode.DRY_RUN)
        self.assertEqual(retrieved.filter_tree, tree)
        self.assertEqual(retrieved.test_cases, test_cases)

    def test_create_with_null_filter_tree(self):
        config = EventFilterConfig.objects.create(team=self.team, mode=EventFilterMode.DISABLED)
        retrieved = EventFilterConfig.objects.get(pk=config.pk)
        self.assertIsNone(retrieved.filter_tree)

    def test_save_prunes_filter_tree(self):
        tree = _and(_cond("event_name", "exact", "pageview"))
        config = EventFilterConfig.objects.create(
            team=self.team,
            mode=EventFilterMode.LIVE,
            filter_tree=tree,
        )
        self.assertEqual(config.filter_tree, _cond("event_name", "exact", "pageview"))

    def test_save_rejects_invalid_filter_tree(self):
        with self.assertRaises(ValidationError):
            EventFilterConfig.objects.create(
                team=self.team,
                mode=EventFilterMode.LIVE,
                filter_tree={"type": "condition", "field": "bad_field", "operator": "exact", "value": "x"},
            )

    def test_save_rejects_invalid_test_cases(self):
        with self.assertRaises(ValidationError):
            EventFilterConfig.objects.create(
                team=self.team,
                mode=EventFilterMode.DISABLED,
                test_cases=[{"expected_result": "maybe"}],
            )

    def test_one_filter_per_team(self):
        EventFilterConfig.objects.create(team=self.team, mode=EventFilterMode.DISABLED)
        with self.assertRaises(Exception):
            EventFilterConfig.objects.create(team=self.team, mode=EventFilterMode.DISABLED)

    def test_update_mode(self):
        config = EventFilterConfig.objects.create(
            team=self.team,
            mode=EventFilterMode.DISABLED,
            filter_tree=_cond(),
        )
        config.mode = EventFilterMode.LIVE
        config.save()
        config.refresh_from_db()
        self.assertEqual(config.mode, EventFilterMode.LIVE)

    def test_str(self):
        config = EventFilterConfig.objects.create(team=self.team, mode=EventFilterMode.DRY_RUN)
        self.assertEqual(str(config), f"EventFilterConfig(team={self.team.id}, mode=dry_run)")
