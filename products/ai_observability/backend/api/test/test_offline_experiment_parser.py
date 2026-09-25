from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ParseError

from products.ai_observability.backend.api.offline_experiment_parser import (
    MAX_UPLOAD_BODY_BYTES,
    OfflineEvaluationJSONParser,
    OfflineEvaluationRequestTooLarge,
)


class TestOfflineEvaluationJSONParser(SimpleTestCase):
    @parameterized.expand([("missing", None), ("understated", "1"), ("overstated", str(MAX_UPLOAD_BODY_BYTES * 2))])
    def test_body_read_is_bounded_independently_of_content_length(self, _name: str, content_length: str | None) -> None:
        metadata = {} if content_length is None else {"CONTENT_LENGTH": content_length}
        stream = BytesIO(b" " * (MAX_UPLOAD_BODY_BYTES + 100))
        with self.assertRaises(OfflineEvaluationRequestTooLarge) as error:
            OfflineEvaluationJSONParser().parse(stream, parser_context={"request": SimpleNamespace(META=metadata)})
        self.assertEqual(error.exception.status_code, 413)
        self.assertEqual(stream.tell(), MAX_UPLOAD_BODY_BYTES + 1)

    def test_body_exactly_at_limit_is_accepted(self) -> None:
        body = b'{"value":0}'
        stream = BytesIO(body + b" " * (MAX_UPLOAD_BODY_BYTES - len(body)))
        self.assertEqual(OfflineEvaluationJSONParser().parse(stream), {"value": 0})

    @parameterized.expand(
        [
            ("malformed", b'{"value":'),
            ("null_body", b"null"),
            ("array_body", b"[]"),
            ("string_body", b'"experiment"'),
            ("number_body", b"1"),
            ("boolean_body", b"true"),
            ("invalid_encoding", b'{"value":"\xff"}'),
            ("nan", b'{"value":NaN}'),
            ("infinity", b'{"value":Infinity}'),
            ("negative_infinity", b'{"value":-Infinity}'),
            ("overflow", b'{"value":1e999}'),
            ("underflow", b'{"value":1e-999}'),
            ("negative_underflow", b'{"value":-1e-999}'),
            ("huge_exponent", b'{"value":1e-999999999999999999999999}'),
            ("nested_nonfinite", b'{"items":[{"payload":{"input":{"value":NaN}}}]}'),
            ("excessive_nesting", b'{"items":' + b"[" * 100_000 + b"0" + b"]" * 100_000 + b"}"),
        ]
    )
    def test_invalid_json_and_unrepresentable_numbers_are_parse_errors(self, _name: str, body: bytes) -> None:
        with self.assertRaises(ParseError):
            OfflineEvaluationJSONParser().parse(BytesIO(body))

    def test_preserves_false_zero_unicode_and_representable_small_numbers(self) -> None:
        body = '{"boolean":false,"integer":0,"float":0.0,"zero_exponent":0e-999,"smallest":5e-324,"text":"café 🦔"}'
        data = OfflineEvaluationJSONParser().parse(BytesIO(body.encode("utf-8")))
        self.assertIs(data["boolean"], False)
        self.assertEqual(data["integer"], 0)
        self.assertEqual(data["float"], 0.0)
        self.assertEqual(data["zero_exponent"], 0.0)
        self.assertEqual(data["smallest"], 5e-324)
        self.assertEqual(data["text"], "café 🦔")
