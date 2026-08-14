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
