import unittest

from common.hogvm.python.utils import unify_comparison_types


class TestUnifyComparisonTypes(unittest.TestCase):
    def test_boolean_string_comparisons(self):
        """Test boolean vs string comparisons handle 'true'/'false' strings correctly"""
        # Boolean False vs string 'true' - the main failing case from logs
        left, right = unify_comparison_types(False, "true")
        assert not left
        assert right

        # Boolean True vs string 'true'
        left, right = unify_comparison_types(True, "true")
        assert left
        assert right

        # Boolean False vs string 'false'
        left, right = unify_comparison_types(False, "false")
        assert not left
        assert not right

        # Boolean True vs string 'false'
        left, right = unify_comparison_types(True, "false")
        assert left
        assert not right

    def test_string_boolean_comparisons(self):
        """Test string vs boolean comparisons handle 'true'/'false' strings correctly"""
        # String 'true' vs boolean False
        left, right = unify_comparison_types("true", False)
        assert left
        assert not right

        # String 'true' vs boolean True
        left, right = unify_comparison_types("true", True)
        assert left
        assert right

        # String 'false' vs boolean False
        left, right = unify_comparison_types("false", False)
        assert not left
        assert not right

        # String 'false' vs boolean True
        left, right = unify_comparison_types("false", True)
        assert not left
        assert right

    def test_case_insensitive_boolean_strings(self):
        """Test case-insensitive handling of 'true'/'false' strings"""
        # Uppercase
        left, right = unify_comparison_types(False, "TRUE")
        assert not left
        assert right

        left, right = unify_comparison_types("FALSE", True)
        assert not left
        assert right

        # Mixed case
        left, right = unify_comparison_types(True, "False")
        assert left
        assert not right

        left, right = unify_comparison_types("True", False)
        assert left
        assert not right

    def test_boolean_number_comparisons(self):
        """Test boolean vs number comparisons (existing functionality)"""
        # Boolean vs integer
        left, right = unify_comparison_types(True, 5)
        assert left == 1
        assert right == 5

        left, right = unify_comparison_types(5, False)
        assert left == 5
        assert right == 0

        # Boolean vs float
        left, right = unify_comparison_types(True, 5.5)
        assert left == 1
        assert right == 5.5

    def test_number_string_comparisons_without_boolean_confusion(self):
        """Test number vs string where strings are not 'true'/'false'"""
        # Number vs numeric string (should convert to float)
        left, right = unify_comparison_types(5, "10")
        assert left == 5
        assert right == 10.0

        # Number vs non-numeric string (should not convert)
        left, right = unify_comparison_types(5, "hello")
        assert left == 5
        assert right == "hello"

        # Non-boolean string vs number (should not convert)
        left, right = unify_comparison_types("hello", 5)
        assert left == "hello"
        assert right == 5

    def test_other_string_vs_boolean(self):
        """Test non-true/false strings vs boolean"""
        # Regular string vs boolean (should use bool() conversion)
        left, right = unify_comparison_types("hello", True)
        assert left  # bool("hello") = True
        assert right

        left, right = unify_comparison_types("", False)
        assert not left  # bool("") = False
        assert not right

        left, right = unify_comparison_types(False, "hello")
        assert not left
        assert right  # bool("hello") = True

    def test_no_conversion_needed(self):
        """Test cases where no type conversion is needed"""
        # Same types
        left, right = unify_comparison_types("hello", "world")
        assert left == "hello"
        assert right == "world"

        left, right = unify_comparison_types(5, 10)
        assert left == 5
        assert right == 10

        left, right = unify_comparison_types(True, False)
        assert left
        assert not right

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


if __name__ == "__main__":
    unittest.main()
