from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.training.recipe_validation import (
    RecipeValidationError,
    validate_feature_sql,
    validate_unique_distinct_ids,
)


class TestRecipeValidation(SimpleTestCase):
    def test_feature_sql_requires_anchors_placeholder(self):
        # labeling substitutes {anchors} with a plain str.replace — a no-op without the
        # placeholder, so the SQL would run with no per-user T0 cutoff (target leakage).
        anchored = "SELECT a.person_id AS distinct_id, count() AS c FROM {anchors} a GROUP BY a.person_id, a.cutoff_ts"
        validate_feature_sql(anchored)

        unanchored = "SELECT person_id AS distinct_id, count() AS c FROM events GROUP BY person_id"
        with self.assertRaises(RecipeValidationError) as ctx:
            validate_feature_sql(unanchored)
        assert "{anchors}" in str(ctx.exception)

    def test_anchors_placeholder_inside_a_comment_does_not_count(self):
        # Substitution strips comments first, so a commented-out placeholder disappears and
        # the query would run over the outcome window.
        commented = (
            "SELECT person_id AS distinct_id, count() AS c FROM events GROUP BY person_id -- reads from {anchors}"
        )
        with self.assertRaises(RecipeValidationError):
            validate_feature_sql(commented)

    @parameterized.expand(
        [
            ("bare_person_id", "SELECT a.person_id FROM {anchors} a"),
            ("other_alias", "SELECT a.person_id AS foo FROM {anchors} a"),
            ("events_distinct_id", "SELECT distinct_id FROM {anchors} a"),
        ]
    )
    def test_feature_sql_requires_person_id_aliased_as_distinct_id(self, _name, sql):
        # The training join reads f.distinct_id and materialization reads that column, so
        # a bare person_id passes recording only to fail fitting and every score run.
        with self.assertRaises(RecipeValidationError) as ctx:
            validate_feature_sql(sql)
        assert "distinct_id" in str(ctx.exception)

    @parameterized.expand(
        [
            (
                "where_clause",
                "SELECT a.person_id AS distinct_id, count() AS c FROM {anchors} a "
                "LEFT JOIN events e ON e.person_id = a.person_id WHERE e.timestamp < now() GROUP BY a.person_id",
            ),
            ("nested_call", "SELECT a.person_id AS distinct_id, toStartOfDay(today()) AS d FROM {anchors} a"),
            (
                "scalar_subquery",
                "SELECT a.person_id AS distinct_id, (SELECT count() FROM events WHERE timestamp < now()) AS c "
                "FROM {anchors} a",
            ),
        ]
    )
    def test_feature_sql_rejects_wall_clock_functions(self, _name, sql):
        # Joining {anchors} proves nothing when the windows are bound to now(): at training
        # time that reads past each user's T0 into the outcome window.
        with self.assertRaises(RecipeValidationError) as ctx:
            validate_feature_sql(sql)
        assert "cutoff_ts" in str(ctx.exception)

    def test_feature_sql_bound_to_cutoff_ts_passes(self):
        validate_feature_sql(
            "SELECT a.person_id AS distinct_id, "
            "dateDiff('day', max(e.timestamp), fromUnixTimestamp(a.cutoff_ts)) AS days_since_last_event "
            "FROM {anchors} a LEFT JOIN events e ON e.person_id = a.person_id "
            "AND e.timestamp < fromUnixTimestamp(a.cutoff_ts) GROUP BY a.person_id, a.cutoff_ts"
        )

    @parameterized.expand(
        [
            ("no_rows", [], None),
            ("unique_rows", [{"distinct_id": "p1"}, {"distinct_id": "p2"}], None),
            ("duplicate_rows", [{"distinct_id": "p1"}, {"distinct_id": "p1"}, {"distinct_id": "p2"}], "p1"),
            # int and str forms of the same id are one person once coerced.
            ("mixed_type_duplicates", [{"distinct_id": 42}, {"distinct_id": "42"}], "42"),
        ]
    )
    def test_unique_distinct_ids(self, _name, rows, expected_duplicate):
        if expected_duplicate is None:
            validate_unique_distinct_ids(rows)
        else:
            with self.assertRaises(RecipeValidationError) as ctx:
                validate_unique_distinct_ids(rows)
            assert expected_duplicate in str(ctx.exception)

    @parameterized.expand([("null", None), ("empty", ""), ("blank", "   ")])
    def test_rows_without_a_person_identifier_are_rejected(self, _name, distinct_id):
        # Such a row joins to no label and no fold, so it would contaminate the holdout with
        # a synthetic person rather than fail the iteration.
        with self.assertRaises(RecipeValidationError) as ctx:
            validate_unique_distinct_ids([{"distinct_id": "p1"}, {"distinct_id": distinct_id}])
        assert "person identifier" in str(ctx.exception)
