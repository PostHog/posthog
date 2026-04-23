import pytest

from dlt.common.normalizers.naming.snake_case import NamingConvention as DltNamingConvention

from posthog.temporal.data_imports.naming_convention import NamingConvention

# Hand-verified outputs — these double as documentation of the convention.
HAND_VERIFIED_CASES = [
    # simple lowercase identifiers pass through
    ("name", "name"),
    ("hello_world", "hello_world"),
    # whitespace is stripped
    ("  padded  ", "padded"),
    # camelCase and PascalCase split on case boundaries
    ("camelCase", "camel_case"),
    ("CamelCase", "camel_case"),
    ("HTTPRequest", "http_request"),
    ("HTTPRequestID", "http_request_id"),
    ("getUserByID", "get_user_by_id"),
    ("parseURLParam", "parse_url_param"),
    ("User2Name", "user2_name"),
    # leading digits get an underscore prefix
    ("123abc", "_123abc"),
    ("1col", "_1col"),
    ("2024_orders", "_2024_orders"),
    # non-alphanumeric characters collapse to underscores
    ("hello world", "hello_world"),
    ("foo.bar.baz", "foo_bar_baz"),
    ("foo/bar", "foo_bar"),
    ("col#1", "col_1"),
    # trailing underscores convert to x's, one per underscore
    ("name_", "namex"),
    ("name__", "namexx"),
    ("trailing___", "trailingxxx"),
    # trailing non-alphanumerics collapse then convert to a single x
    ("col[0]", "col_0x"),
    ("price$", "pricex"),
    ("name (copy)", "name_copyx"),
    # multiple internal underscores collapse to one
    ("foo__bar", "foo_bar"),
    ("foo___bar", "foo_bar"),
    # reduced-alphabet translations happen before non-alnum substitution
    ("a+b", "axb"),
    ("a-b", "a_b"),
    ("a*b", "axb"),
    ("a@b", "aab"),
    ("a|b", "alb"),
    ("C++", "cxx"),
    ("customer@email", "customeraemail"),
    # unicode characters are treated as non-alphanumeric
    ("café", "cafx"),
    # single character and edge inputs
    ("a", "a"),
    ("A", "a"),
    ("1", "_1"),
    ("_", "x"),
    # already snake_case stays stable
    ("already_snake", "already_snake"),
    ("snake_case_123", "snake_case_123"),
    # realistic column names from external sources
    ("Customer ID", "customer_id"),
    ("createdAt", "created_at"),
]


# Cases we don't hardcode — just assert ours matches DLT byte-for-byte.
DLT_PARITY_CASES = [
    "simple",
    "camelCase",
    "HTTPResponse",
    "weird+name-with*chars",
    "name with spaces and 123",
    "Orders (2024) ver 2",
    "My Column-Name+42",
    "UserProfile.firstName",
    "orders[2024]",
    "leadingDigits123Trailing___",
    "a_very_long_identifier_that_should_still_match_dlt_output_exactly",
    "Mix3dC4seWith_Underscores",
    "____only_underscores____",
    "über",
    "A1B2C3",
    "XMLParser",
    "IOError",
    "some+very-mixed*string@with|lots_of#chars!",
    "   leading and trailing   ",
]


class TestNamingConvention:
    def test_none_raises(self):
        with pytest.raises(ValueError, match="`name` is None"):
            NamingConvention.normalize_identifier(None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", ["", " ", "   ", "\t\n"])
    def test_empty_after_strip_raises(self, value):
        with pytest.raises(ValueError):
            NamingConvention.normalize_identifier(value)

    @pytest.mark.parametrize("source,expected", HAND_VERIFIED_CASES)
    def test_hand_verified(self, source, expected):
        assert NamingConvention.normalize_identifier(source) == expected

    @pytest.mark.parametrize("source,_expected", HAND_VERIFIED_CASES)
    def test_hand_verified_matches_dlt(self, source, _expected):
        ours = NamingConvention.normalize_identifier(source)
        theirs = DltNamingConvention().normalize_identifier(source)
        assert ours == theirs

    @pytest.mark.parametrize("source", DLT_PARITY_CASES)
    def test_matches_dlt(self, source):
        ours = NamingConvention.normalize_identifier(source)
        theirs = DltNamingConvention().normalize_identifier(source)
        assert ours == theirs

    def test_default_no_max_length_keeps_long_names(self):
        long_name = "a" * 500
        assert NamingConvention.normalize_identifier(long_name) == long_name

    @pytest.mark.parametrize("max_length", [8, 16, 32, 63, 128])
    def test_max_length_matches_dlt(self, max_length):
        identifier = "this_is_a_fairly_long_identifier_that_needs_to_be_shortened_several_times"
        ours = NamingConvention.normalize_identifier(identifier, max_length=max_length)
        theirs = DltNamingConvention(max_length=max_length).normalize_identifier(identifier)
        assert ours == theirs
        assert len(ours) <= max_length

    def test_max_length_leaves_short_identifiers_alone(self):
        assert NamingConvention.normalize_identifier("short", max_length=32) == "short"

    def test_max_length_tag_is_deterministic(self):
        long_name = "some_really_long_column_name_here"
        first = NamingConvention.normalize_identifier(long_name, max_length=16)
        second = NamingConvention.normalize_identifier(long_name, max_length=16)
        assert first == second
        assert len(first) == 16

    def test_max_length_tag_differs_for_different_inputs(self):
        a = NamingConvention.normalize_identifier("prefix_common_suffix_a", max_length=16)
        b = NamingConvention.normalize_identifier("prefix_common_suffix_b", max_length=16)
        assert a != b
