from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_modeling.backend.logic.column_names import (
    ConflictingColumnNamesError,
    validate_materializable_column_names,
    validate_unique_column_names,
)


class TestValidateUniqueColumnNames(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_duplicate", ["a", "b", "a"], "more than one column named 'a'"),
            # ClickHouse qualifies the unaliased copy when two select items share a name
            ("collision_qualified", ["source_url", "sales.source_url"], "more than one column named 'source_url'"),
            ("several_duplicates", ["a", "a", "b", "b"], "named 'a', 'b'"),
        ]
    )
    def test_rejects_conflicting_names(self, _name, column_names, expected_message):
        with self.assertRaisesMessage(ConflictingColumnNamesError, expected_message):
            validate_unique_column_names(column_names)

    @parameterized.expand(
        [
            ("distinct_names", ["a", "b", "c"]),
            ("empty", []),
            # a dotted name that collides with nothing still backs a schema, so only
            # materialization rejects it
            ("dotted_without_collision", ["sales.source_url", "order_date"]),
        ]
    )
    def test_accepts_usable_names(self, _name, column_names):
        validate_unique_column_names(column_names)


class TestValidateMaterializableColumnNames(SimpleTestCase):
    def test_rejects_a_dotted_name_that_collides_with_nothing(self):
        with self.assertRaisesMessage(ConflictingColumnNamesError, "'sales.source_url'"):
            validate_materializable_column_names(["sales.source_url", "order_date"])

    def test_accepts_distinct_undotted_names(self):
        validate_materializable_column_names(["source_url", "order_date"])
