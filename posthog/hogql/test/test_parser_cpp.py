from ._test_parser import parser_test_factory


class TestParserCpp(parser_test_factory("cpp")):  # type: ignore
    def test_empty(self):
        # this test only exists to make pycharm recognise this class as a test class
        # the actual tests are in the parent class
        pass
