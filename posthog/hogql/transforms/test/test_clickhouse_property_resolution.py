import json

from django.test import SimpleTestCase

from hypothesis import (
    example,
    given,
    settings as hypothesis_settings,
    strategies as st,
)

from posthog.hogql.transforms.clickhouse_property_resolution import _is_json_verbatim

# Plain text alone almost never lands in the accepted set, so bias half the draws to printable ASCII.
_PROPERTY_VALUES = st.one_of(
    st.text(),
    st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E)),
)


class TestJSONVerbatimValues(SimpleTestCase):
    # Producers differ on `ensure_ascii`, and the pre-check runs against whichever one wrote the blob.
    @given(value=_PROPERTY_VALUES)
    @example('some"thing')
    @example("back\\slash")
    @example("sömething")
    @example("tab\there")
    @example("plain_value-1")
    @hypothesis_settings(max_examples=100, deadline=None)
    def test_accepted_values_survive_json_encoding(self, value: str) -> None:
        if not _is_json_verbatim(value):
            return
        assert value in json.dumps({"key": value})
        assert value in json.dumps({"key": value}, ensure_ascii=False)
