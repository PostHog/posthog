import inspect

import pytest
from unittest.mock import patch

from posthog.temporal.common.utils import close_db_connections, make_sync_retryable_with_exponential_backoff


def test_make_sync_retryable_with_exponential_backoff_called_max_attempts():
    """Test function wrapped is called all `max_attempts` times."""
    counter = 0

    def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        make_sync_retryable_with_exponential_backoff(raise_value_error, max_retry_delay=1)()

    assert counter == 5


def test_make_sync_retryable_with_exponential_backoff_called_max_attempts_if_func_returns_retryable():
    """Test function wrapped is called all `max_attempts` times if `is_exception_retryable` returns `True`."""
    counter = 0

    def is_exception_retryable(err):
        return True

    def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        make_sync_retryable_with_exponential_backoff(
            raise_value_error, is_exception_retryable=is_exception_retryable, max_retry_delay=1
        )()

    assert counter == 5


def test_make_sync_retryable_with_exponential_backoff_raises_if_func_returns_not_retryable():
    """Test function wrapped raises immediately if `is_exception_retryable` returns `False`."""
    counter = 0

    def is_exception_retryable(err):
        return False

    def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        make_sync_retryable_with_exponential_backoff(raise_value_error, is_exception_retryable=is_exception_retryable)()

    assert counter == 1


def test_make_sync_retryable_with_exponential_backoff_raises_if_not_retryable():
    """Test function wrapped raises immediately if exception not in `retryable_exceptions`."""
    counter = 0

    def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        make_sync_retryable_with_exponential_backoff(raise_value_error, retryable_exceptions=(TypeError,))()

    assert counter == 1


CLOSE_OLD_CONNECTIONS_TARGET = "posthog.temporal.common.utils.close_old_connections"


@pytest.mark.parametrize(
    "side_effect,expected",
    [
        (None, "ok"),
        (ValueError("boom"), None),
    ],
)
def test_close_db_connections_sync(side_effect, expected):
    def fn(value: str) -> str:
        if side_effect is not None:
            raise side_effect
        return value

    wrapped = close_db_connections(fn)

    with (
        patch(CLOSE_OLD_CONNECTIONS_TARGET) as mock_close,
        patch("posthog.temporal.common.utils.settings.TEST", False),
    ):
        if side_effect is not None:
            with pytest.raises(type(side_effect)):
                wrapped("ok")
        else:
            assert wrapped("ok") == expected

    assert mock_close.call_count == 2


@pytest.mark.parametrize(
    "side_effect,expected",
    [
        (None, "ok"),
        (ValueError("boom"), None),
    ],
)
@pytest.mark.asyncio
async def test_close_db_connections_async(side_effect, expected):
    async def fn(value: str) -> str:
        if side_effect is not None:
            raise side_effect
        return value

    wrapped = close_db_connections(fn)

    with (
        patch(CLOSE_OLD_CONNECTIONS_TARGET) as mock_close,
        patch("posthog.temporal.common.utils.settings.TEST", False),
    ):
        if side_effect is not None:
            with pytest.raises(type(side_effect)):
                await wrapped("ok")
        else:
            assert await wrapped("ok") == expected

    assert mock_close.call_count == 2


def test_close_db_connections_skips_under_test_settings_sync():
    def fn() -> str:
        return "ok"

    wrapped = close_db_connections(fn)

    with (
        patch(CLOSE_OLD_CONNECTIONS_TARGET) as mock_close,
        patch("posthog.temporal.common.utils.settings.TEST", True),
    ):
        assert wrapped() == "ok"

    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_close_db_connections_skips_under_test_settings_async():
    async def fn() -> str:
        return "ok"

    wrapped = close_db_connections(fn)

    with (
        patch(CLOSE_OLD_CONNECTIONS_TARGET) as mock_close,
        patch("posthog.temporal.common.utils.settings.TEST", True),
    ):
        assert await wrapped() == "ok"

    mock_close.assert_not_called()


def test_close_db_connections_preserves_async_signature_for_temporal():
    async def fn() -> str:
        return "ok"

    wrapped = close_db_connections(fn)

    assert inspect.iscoroutinefunction(wrapped)
    assert wrapped.__name__ == "fn"
    assert wrapped.__annotations__ == {"return": str}


def test_close_db_connections_preserves_sync_signature_for_temporal():
    def fn(value: int) -> str:
        return str(value)

    wrapped = close_db_connections(fn)

    assert not inspect.iscoroutinefunction(wrapped)
    assert wrapped.__name__ == "fn"
    assert wrapped.__annotations__ == {"value": int, "return": str}
