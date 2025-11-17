from posthog.test.base import BaseTest

from posthog.hogql.ast import BooleanType, FloatType, IntegerType, StringType
from posthog.hogql.functions.core import AnyConstantType
from posthog.hogql.functions.typegen import generate_json_path_signatures, generate_variadic_signatures


class TestTypegen(BaseTest):
    def test_generate_variadic_signatures_basic(self):
        """Test basic variadic signature generation."""
        # Test with no variadic arguments
        signatures = generate_variadic_signatures(
            fixed_types=[StringType()], variadic_types=[StringType(), IntegerType()], min_variadic=0, max_variadic=0
        )

        self.assertEqual(len(signatures), 1)
        self.assertEqual(len(signatures[0]), 1)
        self.assertIsInstance(signatures[0][0], StringType)

    def test_generate_variadic_signatures_with_variadic(self):
        """Test variadic signature generation with variadic arguments."""
        signatures = generate_variadic_signatures(
            fixed_types=[StringType()], variadic_types=[StringType(), IntegerType()], min_variadic=1, max_variadic=2
        )

        # Should generate:
        # - 1 variadic: (String, String), (String, Integer)
        # - 2 variadic: (String, String, String), (String, String, Integer),
        #               (String, Integer, String), (String, Integer, Integer)
        # Total: 2 + 4 = 6 signatures
        self.assertEqual(len(signatures), 6)

        # Convert to type names for easier comparison
        sig_names = [tuple(type(t).__name__ for t in sig) for sig in signatures]
        expected_names = [
            ("StringType", "StringType"),
            ("StringType", "IntegerType"),
            ("StringType", "StringType", "StringType"),
            ("StringType", "StringType", "IntegerType"),
            ("StringType", "IntegerType", "StringType"),
            ("StringType", "IntegerType", "IntegerType"),
        ]

        self.assertEqual(set(sig_names), set(expected_names))

    def test_generate_json_path_signatures_no_paths(self):
        """Test JSON path signature generation with no paths allowed."""
        signatures = generate_json_path_signatures(
            fixed_types=[StringType()], return_type=IntegerType(), min_paths=0, max_paths=0
        )

        # Should generate only: (StringType,) -> IntegerType
        self.assertEqual(len(signatures), 1)
        inputs, output = signatures[0]
        self.assertEqual(len(inputs), 1)
        self.assertIsInstance(inputs[0], StringType)
        self.assertIsInstance(output, IntegerType)

    def test_generate_json_path_signatures_with_paths(self):
        """Test JSON path signature generation with path arguments."""
        signatures = generate_json_path_signatures(
            fixed_types=[StringType()], return_type=BooleanType(), min_paths=1, max_paths=2
        )

        # Should generate:
        # - 1 path: (String, String) -> Bool, (String, Integer) -> Bool
        # - 2 paths: (String, String, String) -> Bool, (String, String, Integer) -> Bool,
        #           (String, Integer, String) -> Bool, (String, Integer, Integer) -> Bool
        # Total: 2 + 4 = 6 signatures
        self.assertEqual(len(signatures), 6)

        # All should return BooleanType
        for inputs, output in signatures:
            self.assertIsInstance(output, BooleanType)
            # All should start with StringType (JSON parameter)
            self.assertIsInstance(inputs[0], StringType)
            # All should have 2 or 3 total parameters
            self.assertIn(len(inputs), [2, 3])

    def test_generate_json_path_signatures_multiple_fixed(self):
        """Test JSON path signature generation with multiple fixed parameters."""
        signatures = generate_json_path_signatures(
            fixed_types=[StringType(), StringType()],  # JSON + return_type
            return_type=FloatType(),
            min_paths=0,
            max_paths=1,
        )

        # Should generate:
        # - 0 paths: (String, String) -> Float
        # - 1 path: (String, String, String) -> Float, (String, String, Integer) -> Float
        # Total: 1 + 2 = 3 signatures
        self.assertEqual(len(signatures), 3)

        for inputs, output in signatures:
            self.assertIsInstance(output, FloatType)
            # All should start with two StringType parameters
            self.assertIsInstance(inputs[0], StringType)
            self.assertIsInstance(inputs[1], StringType)
            # Should have 2 or 3 total parameters
            self.assertIn(len(inputs), [2, 3])

    def test_generate_json_path_signatures_realistic_jsonhas(self):
        """Test signature generation that matches JSONHas function requirements."""
        signatures = generate_json_path_signatures(
            fixed_types=[StringType()], return_type=IntegerType(), min_paths=1, max_paths=3
        )

        # Should generate signatures for 1, 2, and 3 paths
        # 1 path: 2 signatures
        # 2 paths: 4 signatures
        # 3 paths: 8 signatures
        # Total: 2 + 4 + 8 = 14 signatures
        self.assertEqual(len(signatures), 14)

        # Group by input length
        by_length: dict[int, list[tuple[tuple[AnyConstantType, ...], AnyConstantType]]] = {}
        for inputs, output in signatures:
            length = len(inputs)
            if length not in by_length:
                by_length[length] = []
            by_length[length].append(
                (
                    inputs,
                    output,
                )
            )

        # Check we have the right number for each length
        self.assertEqual(len(by_length[2]), 2)  # 1 path argument
        self.assertEqual(len(by_length[3]), 4)  # 2 path arguments
        self.assertEqual(len(by_length[4]), 8)  # 3 path arguments

    def test_generate_json_path_signatures_edge_cases(self):
        """Test edge cases for JSON path signature generation."""
        # Test with max_paths < min_paths (should generate no signatures)
        signatures = generate_json_path_signatures(
            fixed_types=[StringType()], return_type=IntegerType(), min_paths=3, max_paths=1
        )
        self.assertEqual(len(signatures), 0)

        # Test with min_paths == max_paths
        signatures = generate_json_path_signatures(
            fixed_types=[StringType()], return_type=IntegerType(), min_paths=2, max_paths=2
        )
        # Should generate only signatures with exactly 2 path arguments
        # 2 paths: 2^2 = 4 combinations
        self.assertEqual(len(signatures), 4)
        for inputs, output in signatures:
            self.assertEqual(len(inputs), 3)  # JSON + 2 paths
            self.assertEqual(type(output), IntegerType)
