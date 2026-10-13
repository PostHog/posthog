import asyncio

import pytest

import pyarrow as pa

from products.batch_exports.backend.temporal.utils import JsonType, make_retryable_with_exponential_backoff


async def test_make_retryable_with_exponential_backoff_called_max_attempts():
    """Test function wrapped is called all `max_attempts` times."""
    counter = 0

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(raise_value_error, max_retry_delay=0, max_delay_jitter=0)()

    assert counter == 5


async def test_make_retryable_with_exponential_backoff_called_max_attempts_if_timesout():
    """Test function wrapped is called all `max_attempts` times on a timeout."""
    counter = 0

    async def raise_value_error():
        nonlocal counter
        counter += 1
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        await make_retryable_with_exponential_backoff(
            raise_value_error, max_retry_delay=0, timeout=0.01, max_delay_jitter=0
        )()

    assert counter == 5


async def test_make_retryable_with_exponential_backoff_called_max_attempts_if_func_returns_retryable():
    """Test function wrapped is called all `max_attempts` times if `is_exception_retryable` returns `True`."""
    counter = 0

    def is_exception_retryable(err):
        return True

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(
            raise_value_error, is_exception_retryable=is_exception_retryable, max_retry_delay=0, max_delay_jitter=0
        )()

    assert counter == 5


async def test_make_retryable_with_exponential_backoff_raises_if_func_returns_not_retryable():
    """Test function wrapped raises immediately if `is_exception_retryable` returns `False`."""
    counter = 0

    def is_exception_retryable(err):
        return False

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(
            raise_value_error, is_exception_retryable=is_exception_retryable
        )()

    assert counter == 1


async def test_make_retryable_with_exponential_backoff_raises_if_not_retryable():
    """Test function wrapped raises immediately if exception not in `retryable_exceptions`."""
    counter = 0

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(raise_value_error, retryable_exceptions=(TypeError,))()

    assert counter == 1


@pytest.mark.parametrize(
    "input,expected",
    [
        ([b'{"asdf": "\udee5\ud83e\udee5\\ud83e"}'], [{"asdf": "????"}]),
        ([b'{"asdf": "\\"Hello\\" \\udfa2"}'], [{"asdf": '"Hello" ?'}]),
        ([b'{"asdf": "\n"}'], [{"asdf": "\n"}]),
        ([b'{"asdf": "\\n"}'], [{"asdf": "\n"}]),
        (
            [b'{"finally": "a", "normal": "json", "thing": 1, "bool": false}'],
            [{"finally": "a", "normal": "json", "thing": 1, "bool": False}],
        ),
    ],
)
def test_json_type_as_py(input, expected):
    array = pa.array(input)
    casted_array = array.cast(JsonType())
    result = casted_array.to_pylist()

    assert result == expected
