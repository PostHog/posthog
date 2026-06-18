from ._test_parse_string import parse_string_test_factory


class TestParseStringPython(parse_string_test_factory("cpp")):  # type: ignore
    pass
