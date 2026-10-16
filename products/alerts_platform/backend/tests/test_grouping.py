import hashlib

import pytest

from products.alerts_platform.backend.facade.grouping import bounded_grouping_key, is_hashed_grouping_key

_LONG = "x" * 300
_LONG_DIGEST = f"sha256:{hashlib.sha256(_LONG.encode()).hexdigest()}"


@pytest.mark.parametrize(
    "key, kept",
    [
        ("Chrome", True),
        ('{"service_name":"api"}', True),
        ("x" * 255, True),
        (_LONG, False),
        (_LONG_DIGEST, False),
        ("sha256:", False),
        ("Chr\x00me", False),
        ("Chr\ud800me", False),
    ],
    ids=["plain", "json", "at_limit", "too_long", "literal_digest", "literal_prefix", "nul", "lone_surrogate"],
)
def test_a_key_is_kept_only_when_the_column_can_store_it_and_it_cannot_read_as_a_hash(key: str, kept: bool) -> None:
    bounded = bounded_grouping_key(key)

    assert (bounded == key) is kept
    assert is_hashed_grouping_key(bounded) is not kept
    assert len(bounded) <= 255 and "\x00" not in bounded
    bounded.encode()


def test_a_literal_digest_does_not_share_a_row_with_the_long_key_it_spells() -> None:
    assert bounded_grouping_key(_LONG) == _LONG_DIGEST
    assert bounded_grouping_key(_LONG_DIGEST) != _LONG_DIGEST
