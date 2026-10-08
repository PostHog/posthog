from parameterized import parameterized

from ee.hogai.tools.execute_sql.compatibility_hints import build_compatibility_hint, suggest_cast_type


class TestSuggestCastType:
    @parameterized.expand(
        [
            ("Float64", "Float"),
            ("Float32", "Float"),
            ("Int64", "Int"),
            ("UInt8", "Int"),
            ("Integer", "Int"),
            ("DateTime64", "DateTime"),
            ("Date32", "Date"),
            ("Timestamp", "DateTime"),
            ("Nullable(Float64)", "Float"),
            ("LowCardinality(String)", "String"),
        ]
    )
    def test_maps_clickhouse_spelling_to_hogql(self, type_name: str, expected: str) -> None:
        assert suggest_cast_type(type_name) == expected

    @parameterized.expand([("Map(String, String)",), ("Tuple",), ("Enum8",), ("d",), ("Decimal(10, 2)",)])
    def test_no_suggestion_for_unmappable_type(self, type_name: str) -> None:
        assert suggest_cast_type(type_name) is None


class TestBuildCompatibilityHint:
    def test_none_for_unrelated_error(self) -> None:
        assert build_compatibility_hint("Unknown table `charges`.") is None

    @parameterized.expand(
        [
            ("greatest", "Function 'greatest' expects 2 arguments, found 3", "greatest(x1, greatest(x2, x3))"),
            ("least", "Function 'least' expects 2 arguments, found 3", "least(x1, least(x2, x3))"),
            (
                "four_args",
                "Function 'greatest' expects 2 arguments, found 4",
                "greatest(x1, greatest(x2, greatest(x3, x4)))",
            ),
        ]
    )
    def test_over_arity_suggests_nesting(self, _name: str, message: str, expected_rewrite: str) -> None:
        hint = build_compatibility_hint(message)
        assert hint is not None
        assert expected_rewrite in hint

    def test_under_arity_gets_no_nesting_rewrite(self) -> None:
        # Nesting cannot fix a call that has too few arguments, so the rule must not fire.
        assert build_compatibility_hint("Function 'greatest' expects 2 arguments, found 1") is None

    def test_over_arity_on_other_function_gets_no_nesting_rewrite(self) -> None:
        # `bar` is genuinely 4-argument in ClickHouse too — nesting would be wrong advice.
        assert build_compatibility_hint("Function 'bar' expects 4 arguments, found 5") is None

    def test_bad_escape_suggests_escaped_backslash_and_position(self) -> None:
        hint = build_compatibility_hint("unrecognised escape '\\_'")
        assert hint is not None
        assert "'%\\\\_%'" in hint
        assert "position(" in hint

    def test_bad_cast_names_accepted_types_and_the_rewrite(self) -> None:
        hint = build_compatibility_hint("Unsupported type cast to 'float64'")
        assert hint is not None
        assert "CAST(x AS Float)" in hint
        assert "toFloat(x)" in hint

    @parameterized.expand([("Decimal(10, 2)",), ("Decimal64(4)",), ("Nullable(Decimal(10, 2))",)])
    def test_decimal_cast_points_at_todecimal_and_warns_off_float(self, type_name: str) -> None:
        # Float is an accepted cast name and the nearest spelling, so a prefix match would suggest
        # it. That silently swaps exact decimal arithmetic for binary floating point.
        hint = build_compatibility_hint(f"Unsupported type cast to '{type_name}'")
        assert hint is not None
        assert "toDecimal(x, scale)" in hint
        assert "CAST(x AS Float)" not in hint

    def test_unmappable_cast_still_lists_accepted_types(self) -> None:
        hint = build_compatibility_hint("Unsupported type cast to 'Enum8'")
        assert hint is not None
        assert "Boolean" in hint
        assert "CAST(x AS" not in hint

    def test_hint_is_delimited(self) -> None:
        hint = build_compatibility_hint("Function 'greatest' expects 2 arguments, found 3")
        assert hint is not None
        assert hint.startswith("<hogql_compatibility_hint>")
        assert hint.endswith("</hogql_compatibility_hint>")
