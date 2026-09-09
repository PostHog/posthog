from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.training.recipe_validation import (
    RecipeValidationError,
    validate_feature_sql,
    validate_recipe,
    validate_unique_distinct_ids,
)

ANCHORED = "SELECT a.person_id AS distinct_id, count() AS c FROM {anchors} a GROUP BY a.person_id, a.cutoff_ts"


class TestRecipeValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("absent", "SELECT person_id AS distinct_id, count() AS c FROM events GROUP BY person_id"),
            (
                "in_a_comment",
                "SELECT person_id AS distinct_id, count() AS c FROM events GROUP BY person_id -- reads from {anchors}",
            ),
            ("in_a_string_literal", "SELECT e.person_id AS distinct_id, '{anchors}' AS marker FROM events e"),
        ]
    )
    def test_anchors_placeholder_must_be_a_table_source(self, _name, sql):
        # labeling substitutes {anchors} in code position only; without it as a table the SQL
        # runs with no per-user T0 cutoff (target leakage).
        with self.assertRaises(RecipeValidationError) as ctx:
            validate_feature_sql(sql)
        assert "{anchors}" in str(ctx.exception)

    @parameterized.expand(
        [
            ("bare_person_id", "SELECT a.person_id FROM {anchors} a"),
            ("other_alias", "SELECT a.person_id AS foo FROM {anchors} a"),
            ("events_distinct_id", "SELECT distinct_id FROM {anchors} a"),
            ("transformed", "SELECT toString(a.person_id) AS distinct_id FROM {anchors} a"),
            (
                "joined_relations_key",
                "SELECT e.person_id AS distinct_id FROM {anchors} a LEFT JOIN events e ON e.person_id = a.person_id",
            ),
            ("selected_twice", "SELECT a.person_id AS distinct_id, a.person_id AS distinct_id FROM {anchors} a"),
        ]
    )
    def test_feature_sql_requires_the_anchor_person_id_aliased_as_distinct_id(self, _name, sql):
        # The training join reads f.distinct_id and materialization reads that column: a bare
        # person_id fails fitting, and a transformed or foreign key is unique yet joins to no label.
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
            ("upper_case", "SELECT a.person_id AS distinct_id, NOW() AS t FROM {anchors} a"),
            ("alias_resolving_to_now", "SELECT a.person_id AS distinct_id, current_timestamp() AS t FROM {anchors} a"),
            ("bare_keyword", "SELECT a.person_id AS distinct_id, CURRENT_DATE AS d FROM {anchors} a"),
        ]
    )
    def test_feature_sql_rejects_wall_clock_reads(self, _name, sql):
        # Joining {anchors} proves nothing when the windows are bound to now(): at training
        # time that reads past each user's T0 into the outcome window.
        with self.assertRaises(RecipeValidationError) as ctx:
            validate_feature_sql(sql)
        assert "cutoff_ts" in str(ctx.exception)

    @parameterized.expand(
        [
            (
                "bound_to_cutoff_ts",
                "SELECT a.person_id AS distinct_id, "
                "dateDiff('day', max(e.timestamp), fromUnixTimestamp(a.cutoff_ts)) AS days_since_last_event "
                "FROM {anchors} a LEFT JOIN events e ON e.person_id = a.person_id "
                "AND e.timestamp < fromUnixTimestamp(a.cutoff_ts) GROUP BY a.person_id, a.cutoff_ts",
            ),
            (
                "other_placeholders",
                "SELECT a.person_id AS distinct_id, count(e.uuid) AS n FROM {anchors} a LEFT JOIN events e "
                "ON e.person_id = a.person_id AND e.timestamp >= fromUnixTimestamp(a.cutoff_ts) "
                "- toIntervalDay({lookback_days}) GROUP BY a.person_id",
            ),
            (
                "anchors_behind_a_cte",
                "WITH base AS (SELECT person_id, cutoff_ts FROM {anchors}) "
                "SELECT b.person_id AS distinct_id, b.cutoff_ts AS t FROM base b",
            ),
            ("unaliased_anchors", "SELECT person_id AS distinct_id FROM {anchors}"),
        ]
    )
    def test_feature_sql_shapes_that_keep_the_contract_pass(self, _name, sql):
        validate_feature_sql(sql)

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

    @parameterized.expand([("every_anchor_covered", 2, False), ("anchor_dropped", 3, True), ("extra_person", 1, True)])
    def test_expected_count_requires_one_row_per_anchor(self, _name, expected_count, rejected):
        rows = [{"distinct_id": "p1"}, {"distinct_id": "p2"}]
        if not rejected:
            validate_unique_distinct_ids(rows, expected_count=expected_count)
            return
        with self.assertRaises(RecipeValidationError) as ctx:
            validate_unique_distinct_ids(rows, expected_count=expected_count)
        assert str(expected_count) in str(ctx.exception)

    @parameterized.expand(
        [
            ("model_spec_not_an_object", ["sklearn"], {"feature_sql": ANCHORED}),
            ("model_class_missing", {}, {"feature_sql": ANCHORED}),
            ("model_class_not_a_string", {"model_class": ["a"]}, {"feature_sql": ANCHORED}),
            ("recipe_not_an_object", {"model_class": "m"}, "SELECT 1"),
            ("feature_sql_missing", {"model_class": "m"}, {}),
            ("feature_sql_not_a_string", {"model_class": "m"}, {"feature_sql": 1}),
            ("feature_sql_blank", {"model_class": "m"}, {"feature_sql": "  "}),
        ]
    )
    def test_validate_recipe_rejects_malformed_agent_input(self, _name, model_spec, recipe_snapshot):
        with self.assertRaises(RecipeValidationError):
            validate_recipe(model_spec, recipe_snapshot)

    def test_validate_recipe_accepts_a_valid_iteration(self):
        validate_recipe({"model_class": "sklearn.linear_model.LogisticRegression"}, {"feature_sql": ANCHORED})
