from posthog.test.base import BaseTest

from parameterized import parameterized

from products.autoresearch.backend.labeling import _substitute_anchors, build_inference_features_sql, strip_sql_comments


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
