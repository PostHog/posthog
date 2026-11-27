import re

import pytest

from parameterized import parameterized

from products.ai_observability.backend.logic.diagnostics.entity_keys import (
    MalformedEntityKeyError,
    decode_entity_key,
    encode_entity_key,
)


def test_entity_key_round_trips_long_unicode_with_newlines() -> None:
    message = 'Tool "lookup" failed at 100% load:\nCaché inválida ✗ / retry? ' * 40

    key = encode_entity_key(message)

    assert re.fullmatch(r"[A-Za-z0-9_-]+", key)
    assert decode_entity_key(key) == message


@parameterized.expand(
    [
        ("empty", ""),
        ("padded", "QQ=="),
        ("standard_alphabet", "a+b/"),
        ("impossible_length", "QUFBQ"),
        ("non_canonical_trailing_bits", "QR"),
        ("invalid_utf8", "_w"),
    ]
)
def test_a_key_that_names_no_message_is_malformed(_name: str, key: str) -> None:
    with pytest.raises(MalformedEntityKeyError):
        decode_entity_key(key)
