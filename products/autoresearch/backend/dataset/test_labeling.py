from typing import Any

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.dataset.labeling import (
    _build_labeled_users_cte,
    _substitute_anchors,
    build_eligible_count_sql,
    build_inference_anchors_sql,
    build_inference_features_sql,
    strip_sql_comments,
)


class TestStripSqlComments(BaseTest):
    @parameterized.expand(
        [
            ("line_comment", "SELECT a -- the count\nFROM t", "SELECT a \nFROM t"),
            ("block_comment", "SELECT a /* inline */ FROM t", "SELECT a   FROM t"),
            ("trailing_line_comment", "SELECT a FROM t -- trailing", "SELECT a FROM t "),
            ("no_comment", "SELECT a FROM t", "SELECT a FROM t"),
        ]
    )
    def test_strips_comments(self, _name: str, sql: str, expected: str) -> None:
        self.assertEqual(strip_sql_comments(sql), expected)

    def test_preserves_double_dash_inside_string_literal(self) -> None:
        sql = "SELECT 'a -- b' AS x FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)

    def test_preserves_escaped_quote_inside_string(self) -> None:
        sql = "SELECT 'it''s -- fine' AS x FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)

    def test_preserves_block_comment_markers_inside_string(self) -> None:
        sql = "SELECT '/* not a comment */' AS x FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)

    def test_preserves_double_dash_inside_backtick_identifier(self) -> None:
        sql = "SELECT `weird--name` FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)


class TestSubstituteAnchors(BaseTest):
    def test_placeholder_in_line_comment_does_not_corrupt_substitution(self) -> None:
        # A multi-line anchors subquery substituted into a `--` comment would
        # escape the comment and break the parse — stripping comments first avoids it.
        feature_sql = "SELECT a.person_id AS distinct_id\n-- read FROM {anchors} a here\nFROM {anchors} a"
        anchors = "(SELECT person_id, t0_ts AS cutoff_ts\nFROM labeled_anchors)"
        result = _substitute_anchors(feature_sql, anchors)
        self.assertNotIn("--", result)
        # The real FROM {anchors} got substituted; the commented one was removed.
        self.assertEqual(result.count("labeled_anchors"), 1)

    def test_substitutes_all_real_occurrences(self) -> None:
        feature_sql = "SELECT * FROM {anchors} a JOIN {anchors} b ON a.person_id = b.person_id"
        result = _substitute_anchors(feature_sql, "(SELECT 1)")
        self.assertEqual(result.count("(SELECT 1)"), 2)
        self.assertNotIn("{anchors}", result)


class TestBuildInferenceFeaturesSql(BaseTest):
    def test_comment_in_feature_sql_is_stripped_before_substitution(self) -> None:
        feature_sql = "SELECT a.person_id AS distinct_id -- {anchors}\nFROM {anchors} a"
        sql, _values = build_inference_features_sql(
            feature_sql=feature_sql,
            lookback_days=30,
            inference_population=None,
        )
        self.assertNotIn("{anchors}", sql)
        self.assertNotIn("--", sql)


class TestPopulationKindCompilation(SimpleTestCase):
    # Guards against the regression where a semantic population spec ({"kind": ...})
    # fell through the compiler and silently widened to "all identified users".

    @parameterized.expand(
        [
            (
                "performed_any_event",
                {"kind": "performed_event_within_days", "days": 30},
                ["person_id IN (SELECT DISTINCT person_id FROM events"],
                {"popk_days": 30},
            ),
            (
                "performed_specific_event",
                {"kind": "performed_event_within_days", "days": 30, "event": "$pageview"},
                ["person_id IN (SELECT DISTINCT person_id FROM events", "event = {popk_event}"],
                {"popk_days": 30, "popk_event": "$pageview"},
            ),
            (
                "first_seen",
                {"kind": "person_first_seen_within_days", "days": 14},
                ["person.created_at >= now() - toIntervalDay({popk_days})"],
                {"popk_days": 14},
            ),
            (
                "active_not_performed_target",
                {"kind": "active_not_performed_target", "active_within_days": 30, "event": "feature_used"},
                ["person_id IN (SELECT DISTINCT person_id FROM events", "person_id NOT IN", "event = {popk_event}"],
                {"popk_active_days": 30, "popk_event": "feature_used"},
            ),
            (
                "ever_performed_event",
                {"kind": "ever_performed_event", "event": "checkout"},
                ["person_id IN (SELECT DISTINCT person_id FROM events", "event = {popk_event}"],
                {"popk_event": "checkout"},
            ),
        ]
    )
    def test_inference_anchors_filter_kind_population(
        self,
        _name: str,
        population: dict[str, Any],
        fragments: list[str],
        expected_values: dict[str, Any],
    ) -> None:
        sql, values = build_inference_anchors_sql(lookback_days=90, inference_population=population)
        for fragment in fragments:
            self.assertIn(fragment, sql)
        for key, expected in expected_values.items():
            self.assertEqual(values[key], expected)

    def test_eligible_count_filters_kind_population(self) -> None:
        sql, values = build_eligible_count_sql(
            horizon_days=7,
            lookback_days=90,
            training_population={"kind": "performed_event_within_days", "days": 30},
        )
        self.assertIn("person_id IN (SELECT DISTINCT person_id FROM events", sql)
        self.assertEqual(values["popk_days"], 30)

    def test_inference_backfill_anchors_kind_windows_at_cutoff(self) -> None:
        sql, _values = build_inference_anchors_sql(
            lookback_days=90,
            inference_population={"kind": "performed_event_within_days", "days": 30},
            cutoff_ts=1_700_000_000,
        )
        self.assertIn("timestamp >= fromUnixTimestamp({cutoff_ts}) - toIntervalDay({popk_days})", sql)

    @parameterized.expand(
        [
            ("unknown_kind", {"kind": "bogus"}),
            ("missing_days", {"kind": "performed_event_within_days"}),
            ("non_int_days", {"kind": "person_first_seen_within_days", "days": "14"}),
            ("missing_active_days", {"kind": "active_not_performed_target", "event": "x"}),
            ("missing_event", {"kind": "ever_performed_event"}),
        ]
    )
    def test_uncompilable_kind_raises_instead_of_widening(self, _name: str, population: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            build_inference_anchors_sql(lookback_days=90, inference_population=population)


class TestPopulationKindTrainingSemantics(SimpleTestCase):
    # Training must evaluate target-relative membership per user at T0. A row-level
    # "has not performed the target" filter would delete exactly the users whose
    # post-T0 adoption provides the positive labels.

    def test_adoption_kind_excludes_pre_t0_performers_via_having(self) -> None:
        cte, values = _build_labeled_users_cte(
            target_event="feature_used",
            target_definition=None,
            team=None,
            horizon_days=7,
            lookback_days=90,
            training_population={
                "kind": "active_not_performed_target",
                "active_within_days": 30,
                "event": "feature_used",
            },
            sample_limit=None,
        )
        self.assertIn("HAVING max((event = {target}) AND toInt(toUnixTimestamp(e.timestamp)) < u.t0_ts) = 0", cte)
        self.assertNotIn("NOT IN", cte)
        self.assertEqual(values["popk_active_days"], 30)

    def test_repeat_kind_requires_pre_t0_performance_via_having(self) -> None:
        cte, _values = _build_labeled_users_cte(
            target_event="checkout",
            target_definition=None,
            team=None,
            horizon_days=7,
            lookback_days=90,
            training_population={"kind": "ever_performed_event", "event": "checkout"},
            sample_limit=None,
        )
        self.assertIn("HAVING max((event = {target}) AND toInt(toUnixTimestamp(e.timestamp)) < u.t0_ts) = 1", cte)
        self.assertIn("person_id IN (SELECT DISTINCT person_id FROM events", cte)

    def test_kind_and_property_filters_compose(self) -> None:
        cte, values = _build_labeled_users_cte(
            target_event="checkout",
            target_definition=None,
            team=None,
            horizon_days=7,
            lookback_days=90,
            training_population={
                "kind": "performed_event_within_days",
                "days": 30,
                "properties": [{"key": "email", "type": "person", "operator": "is_set"}],
            },
            sample_limit=None,
        )
        self.assertIn("person_id IN (SELECT DISTINCT person_id FROM events", cte)
        self.assertIn("isNotNull(person.properties[{pop_k_0}])", cte)
        self.assertEqual(values["popk_days"], 30)
