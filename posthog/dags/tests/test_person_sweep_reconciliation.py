from contextvars import ContextVar

import pytest

from posthog.dags.person_sweep_reconciliation import _fan_out

_caller_tag: ContextVar[str] = ContextVar("caller_tag", default="unset")


@pytest.mark.parametrize("concurrency", [1, 3])
def test_fan_out_keeps_order_and_the_callers_context(concurrency: int) -> None:
    token = _caller_tag.set("sweep")
    try:
        results = _fan_out(lambda chunk: (chunk, _caller_tag.get()), [1, 2, 3, 4], concurrency)
    finally:
        _caller_tag.reset(token)

    assert results == [(1, "sweep"), (2, "sweep"), (3, "sweep"), (4, "sweep")]


def test_fan_out_fails_when_any_chunk_fails() -> None:
    def lookup(chunk: int) -> int:
        if chunk == 2:
            raise ConnectionError("replica unavailable")
        return chunk

    with pytest.raises(ConnectionError):
        _fan_out(lookup, [1, 2, 3], concurrency=3)
