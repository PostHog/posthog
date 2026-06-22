from ._test_parse_string import parse_string_test_factory


class TestParseStringRust(parse_string_test_factory("rust-json")):  # type: ignore
    pass
