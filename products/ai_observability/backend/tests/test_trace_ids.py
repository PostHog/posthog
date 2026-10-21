from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.presentation.trace_ids import (
    MalformedTraceIdSegmentError,
    decode_trace_id_segment,
)


class TestDecodeTraceIdSegment(SimpleTestCase):
    @parameterized.expand(
        [
            ("abc", "YWJj"),
            ("run.42", "cnVuLjQy"),
            ("a b#c", "YSBiI2M"),
            ("a/b", "YS9i"),
            (".", "Lg"),
            ("é/ü", "w6kvw7w"),
        ]
    )
    def test_decodes_the_shared_vectors(self, trace_id: str, segment: str) -> None:
        assert decode_trace_id_segment(segment) == trace_id

    @parameterized.expand(
        [
            ("characters outside base64url", "YS9i+"),
            ("impossible length", "YS9iY"),
            ("bytes that are not utf-8", "_w"),
        ]
    )
    def test_rejects_a_malformed_segment(self, _name: str, segment: str) -> None:
        with self.assertRaises(MalformedTraceIdSegmentError):
            decode_trace_id_segment(segment)
