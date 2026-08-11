import unittest

from parameterized import parameterized

from common.hogvm.python.stl.date import to_hog_datetime
from common.hogvm.python.utils import unify_comparison_types


class TestUnifyComparisonTypes(unittest.TestCase):
    def test_boolean_string_comparisons(self):
        """Test boolean vs string comparisons handle 'true'/'false' strings correctly"""
        # Boolean False vs string 'true' - the main failing case from logs
        left, right = unify_comparison_types(False, "true")
        self.assertEqual(left, False)
        self.assertEqual(right, True)

        # Boolean True vs string 'true'
        left, right = unify_comparison_types(True, "true")
        self.assertEqual(left, True)
        self.assertEqual(right, True)

        # Boolean False vs string 'false'
        left, right = unify_comparison_types(False, "false")
        self.assertEqual(left, False)
        self.assertEqual(right, False)

        # Boolean True vs string 'false'
        left, right = unify_comparison_types(True, "false")
        self.assertEqual(left, True)
        self.assertEqual(right, False)

    def test_string_boolean_comparisons(self):
        """Test string vs boolean comparisons handle 'true'/'false' strings correctly"""
        # String 'true' vs boolean False
        left, right = unify_comparison_types("true", False)
        self.assertEqual(left, True)
        self.assertEqual(right, False)

        # String 'true' vs boolean True
        left, right = unify_comparison_types("true", True)
        self.assertEqual(left, True)
        self.assertEqual(right, True)

        # String 'false' vs boolean False
        left, right = unify_comparison_types("false", False)
        self.assertEqual(left, False)
        self.assertEqual(right, False)

        # String 'false' vs boolean True
        left, right = unify_comparison_types("false", True)
        self.assertEqual(left, False)
        self.assertEqual(right, True)

    def test_case_insensitive_boolean_strings(self):
        """Test case-insensitive handling of 'true'/'false' strings"""
        # Uppercase
        left, right = unify_comparison_types(False, "TRUE")
        self.assertEqual(left, False)
        self.assertEqual(right, True)

        left, right = unify_comparison_types("FALSE", True)
        self.assertEqual(left, False)
        self.assertEqual(right, True)

        # Mixed case
        left, right = unify_comparison_types(True, "False")
        self.assertEqual(left, True)
        self.assertEqual(right, False)

        left, right = unify_comparison_types("True", False)
        self.assertEqual(left, True)
        self.assertEqual(right, False)

    def test_boolean_number_comparisons(self):
        """Test boolean vs number comparisons (existing functionality)"""
        # Boolean vs integer
        left, right = unify_comparison_types(True, 5)
        self.assertEqual(left, 1)
        self.assertEqual(right, 5)

        left, right = unify_comparison_types(5, False)
        self.assertEqual(left, 5)
        self.assertEqual(right, 0)

        # Boolean vs float
        left, right = unify_comparison_types(True, 5.5)
        self.assertEqual(left, 1)
        self.assertEqual(right, 5.5)

    def test_number_string_comparisons_without_boolean_confusion(self):
        """Test number vs string where strings are not 'true'/'false'"""
        # Number vs numeric string (should convert to float)
        left, right = unify_comparison_types(5, "10")
        self.assertEqual(left, 5)
        self.assertEqual(right, 10.0)

        # Number vs non-numeric string (should not convert)
        left, right = unify_comparison_types(5, "hello")
        self.assertEqual(left, 5)
        self.assertEqual(right, "hello")

        # Non-boolean string vs number (should not convert)
        left, right = unify_comparison_types("hello", 5)
        self.assertEqual(left, "hello")
        self.assertEqual(right, 5)

    def test_other_string_vs_boolean(self):
        """Test non-true/false strings vs boolean"""
        # Regular string vs boolean (should use bool() conversion)
        left, right = unify_comparison_types("hello", True)
        self.assertEqual(left, True)  # bool("hello") = True
        self.assertEqual(right, True)

        left, right = unify_comparison_types("", False)
        self.assertEqual(left, False)  # bool("") = False
        self.assertEqual(right, False)

        left, right = unify_comparison_types(False, "hello")
        self.assertEqual(left, False)
        self.assertEqual(right, True)  # bool("hello") = True

    def test_no_conversion_needed(self):
        """Test cases where no type conversion is needed"""
        # Same types
        left, right = unify_comparison_types("hello", "world")
        self.assertEqual(left, "hello")
        self.assertEqual(right, "world")

        left, right = unify_comparison_types(5, 10)
        self.assertEqual(left, 5)
        self.assertEqual(right, 10)

        left, right = unify_comparison_types(True, False)
        self.assertEqual(left, True)
        self.assertEqual(right, False)

    def test_no_float_conversion_errors(self):
        """Test that we don't get float conversion errors for boolean strings"""
        # These should not raise ValueError about converting string to float
        try:
            unify_comparison_types(5, "true")
            unify_comparison_types("false", 10)
            unify_comparison_types(False, "true")
            unify_comparison_types("false", True)
        except ValueError as e:
            if "could not convert string to float" in str(e):
                self.fail(f"Float conversion error should not occur: {e}")


class TestUnifyComparisonTypesTemporalOrdering(unittest.TestCase):
    # Regression: a hand-written SQL trigger filter like `timestamp > toDateTime('2026-06-01')` only
    # wraps the RHS in toDateTime, so the VM ends up unifying a plain ISO string against a HogDateTime
    # dict. Before this fix, HogDateTime dicts fell through unify_comparison_types unchanged and the
    # ordering operators tried to compare a str to a dict, raising a TypeError.
    later_datetime = to_hog_datetime(1782988689)  # 2026-06-28
    earlier_datetime = to_hog_datetime(1782518400)  # 2026-06-23 00:00:00 UTC
    later_iso_timestamp = "2026-06-28T00:00:00.000Z"  # same instant as later_datetime
    earlier_iso_timestamp = "2026-06-23T00:00:00.000Z"  # same instant as earlier_datetime

    @parameterized.expand(
        [
            ("HogDateTime vs HogDateTime", later_datetime, earlier_datetime),
            ("string vs HogDateTime", later_iso_timestamp, earlier_datetime),
            ("HogDateTime vs string", later_datetime, earlier_iso_timestamp),
        ]
    )
    def test_orders_chronologically(self, _label, later, earlier):
        left, right = unify_comparison_types(later, earlier)
        self.assertGreater(left, right)

    def test_non_date_string_against_temporal_value_falls_through_unchanged(self):
        left, right = unify_comparison_types("not-a-date", self.later_datetime)
        self.assertEqual(left, "not-a-date")
        self.assertEqual(right, self.later_datetime)


if __name__ == "__main__":
    unittest.main()
