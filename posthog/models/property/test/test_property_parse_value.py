from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.property import Property


class TestPropertyParseValue(BaseTest):
    """Test the Property._parse_value method to ensure it handles all edge cases correctly."""

    @parameterized.expand(
        [
            # Basic types
            ("string_value", "hello", "hello"),
            ("integer_value", 42, 42),
            ("float_value", 3.14, 3.14),
            # Boolean values
            ("boolean_true_string", "true", True),
            ("boolean_false_string", "false", False),
            ("boolean_true_capitalized", "True", True),
            ("boolean_false_capitalized", "False", False),
            ("boolean_true_value", True, True),
            ("boolean_false_value", False, False),
            # Lists
            ("list_of_strings", ["a", "b", "c"], ["a", "b", "c"]),
            ("list_of_numbers", [1, 2, 3], [1, 2, 3]),
            ("list_with_booleans", ["true", "false", True, False], [True, False, True, False]),
            # Number strings that should remain strings
            ("number_string_int", "123", "123"),
            ("number_string_float", "123.45", "123.45"),
            ("number_string_zero", "0", "0"),
            ("number_string_negative", "-42", "-42"),
            # Scientific notation strings that should NOT be converted to infinity
            ("scientific_notation_small", "1e10", "1e10"),
            ("scientific_notation_large", "68220362511491315356e330", "68220362511491315356e330"),
            ("scientific_notation_negative", "-1e10", "-1e10"),
            ("scientific_notation_uppercase", "1E10", "1E10"),
            ("scientific_notation_positive_sign", "+1e10", "+1e10"),
            # Edge cases that would convert to infinity
            ("another_infinity_string", "1e400", "1e400"),
            ("negative_infinity_string", "-1e400", "-1e400"),
            # JSON-like strings (these should be parsed)
            ("json_string", '{"key": "value"}', {"key": "value"}),
            ("json_array", '["a", "b", "c"]', ["a", "b", "c"]),
            ("json_number", "42", "42"),  # Should remain string when not convert_to_number
            # Special characters and edge cases
            ("empty_string", "", ""),
            ("whitespace", "   ", "   "),
            ("special_chars", "!@#$%^&*()", "!@#$%^&*()"),
            ("unicode", "🚀", "🚀"),
            # None values
            ("none_value", None, None),
        ]
    )
    def test_parse_value_without_convert_to_number(self, name, input_value, expected):
        """Test _parse_value with convert_to_number=False (default)."""
        result = Property._parse_value(input_value, convert_to_number=False)
        self.assertEqual(result, expected, f"Failed for {name}: {input_value}")

    @parameterized.expand(
        [
            # Numbers that should be converted
            ("number_string_int", "123", 123),
            ("number_string_float", "123.45", 123.45),
            ("number_string_zero", "0", 0),
            ("number_string_negative", "-42", -42),
            # Scientific notation that should NOT convert to infinity
            ("scientific_notation_small", "1e10", 10000000000.0),  # Small scientific notation is converted normally
            (
                "scientific_notation_large",
                "68220362511491315356e330",
                "68220362511491315356e330",
            ),  # Should remain string
            (
                "scientific_notation_negative",
                "-1e10",
                -10000000000.0,
            ),  # Small negative scientific notation is converted normally
            # JSON values that convert to numbers
            ("json_number", "42", 42),
            ("json_float", "3.14", 3.14),
            # Non-numeric strings that should remain strings
            ("non_numeric_string", "hello", "hello"),
            ("mixed_string", "123abc", "123abc"),
            # Boolean values
            ("boolean_true_string", "true", True),
            ("boolean_false_string", "false", False),
            # Lists should be processed recursively
            ("list_with_numbers", ["1", "2", "3"], [1, 2, 3]),
            ("list_with_mixed", ["1", "hello", "3.14"], [1, "hello", 3.14]),
        ]
    )
    def test_parse_value_with_convert_to_number(self, name, input_value, expected):
        """Test _parse_value with convert_to_number=True."""
        result = Property._parse_value(input_value, convert_to_number=True)
        self.assertEqual(result, expected, f"Failed for {name}: {input_value}")

    def test_infinity_prevention_without_convert_to_number(self):
        """Test that scientific notation strings that would become infinity are kept as strings."""
        test_cases = [
            "68220362511491315356e330",  # The exact problematic value from the issue
            "1e400",  # Another value that would become infinity
            "-1e400",  # Negative infinity
            "1E400",  # Uppercase E
            "999999999999999999999e999",  # Another large scientific notation
        ]

        for value in test_cases:
            with self.subTest(value=value):
                result = Property._parse_value(value, convert_to_number=False)
                self.assertEqual(result, value, f"Value {value} should remain as string")
                self.assertIsInstance(result, str, f"Value {value} should be a string, got {type(result)}")

    def test_infinity_prevention_with_convert_to_number(self):
        """Test that scientific notation strings that would become infinity are kept as strings even with convert_to_number=True."""
        test_cases = [
            "68220362511491315356e330",  # The exact problematic value from the issue
            "1e400",  # Another value that would become infinity
            "-1e400",  # Negative infinity
            "1E400",  # Uppercase E
            "999999999999999999999e999",  # Another large scientific notation
        ]

        for value in test_cases:
            with self.subTest(value=value):
                result = Property._parse_value(value, convert_to_number=True)
                self.assertEqual(result, value, f"Value {value} should remain as string to prevent infinity")
                self.assertIsInstance(result, str, f"Value {value} should be a string, got {type(result)}")

    def test_normal_scientific_notation_conversion(self):
        """Test that normal scientific notation that doesn't result in infinity is converted properly."""
        test_cases = [
            ("1e2", 100.0),
            ("1e-2", 0.01),
            ("2.5e3", 2500.0),
            ("-1e2", -100.0),
            ("1.23e4", 12300.0),
        ]

        for value, expected in test_cases:
            with self.subTest(value=value):
                result = Property._parse_value(value, convert_to_number=True)
                self.assertEqual(result, expected, f"Value {value} should convert to {expected}")
                self.assertIsInstance(result, (int, float), f"Value {value} should be numeric, got {type(result)}")

    def test_recursive_list_processing(self):
        """Test that lists are processed recursively."""
        input_list: Any = [
            "68220362511491315356e330",  # Should remain string
            "123",  # Should convert to number with convert_to_number=True
            "hello",  # Should remain string
            ["nested", "1e400"],  # Nested list with infinity-causing value
        ]

        # Without convert_to_number
        result = Property._parse_value(input_list, convert_to_number=False)
        expected: Any = [
            "68220362511491315356e330",
            "123",  # Remains string
            "hello",
            ["nested", "1e400"],  # Nested values remain strings
        ]
        self.assertEqual(result, expected)

        # With convert_to_number
        result = Property._parse_value(input_list, convert_to_number=True)
        expected = [
            "68220362511491315356e330",  # Should remain string to prevent infinity
            123,  # Should convert to number
            "hello",
            ["nested", "1e400"],  # Nested infinity-causing value should remain string
        ]
        self.assertEqual(result, expected)

    def test_json_parsing_with_infinity_prevention(self):
        """Test that JSON parsing also prevents infinity conversion."""
        # Test simple JSON number that would cause infinity
        large_number_string = "68220362511491315356e330"
        result = Property._parse_value(large_number_string, convert_to_number=True)

        # Should remain as string to prevent infinity
        self.assertEqual(result, large_number_string)
        self.assertIsInstance(result, str, "The problematic value should remain a string")

        # Test JSON object with infinity-causing value
        json_with_large_number = '{"id": "68220362511491315356e330"}'
        result = Property._parse_value(json_with_large_number, convert_to_number=True)
        expected = {"id": "68220362511491315356e330"}
        self.assertEqual(result, expected)
        self.assertIsInstance(result["id"], str, "The problematic value should remain a string")

    def test_edge_cases(self):
        """Test various edge cases."""
        # Empty values
        self.assertIsNone(Property._parse_value(None))
        self.assertEqual(Property._parse_value(""), "")

        # Invalid JSON
        invalid_json = '{"invalid": json}'
        result = Property._parse_value(invalid_json, convert_to_number=True)
        self.assertEqual(result, invalid_json, "Invalid JSON should remain as string")

        # Already parsed values
        self.assertEqual(Property._parse_value(123), 123)
        self.assertEqual(Property._parse_value(3.14), 3.14)
        self.assertEqual(Property._parse_value(True), True)
