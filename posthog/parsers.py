from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class SafeJSONParser(JSONParser):
    """JSON parser that turns a RecursionError into a 400 instead of a 500.

    A deeply nested JSON body makes ``json.loads`` raise ``RecursionError``, which
    is not a ``ValueError``, so DRF's ``JSONParser`` lets it escape as an unhandled
    500. This parser catches it and returns a clean 400.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        try:
            return super().parse(stream, media_type, parser_context)
        except RecursionError:
            raise ParseError("JSON parse error - Maximum recursion depth exceeded")
