import errno

import pytest

from posthog.temporal.common import metrics_bind
from posthog.temporal.common.metrics_bind import bind_with_retry, is_address_in_use_error


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    monkeypatch.setattr(metrics_bind, "BIND_BACKOFF_SECONDS", 0.0)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (OSError(errno.EADDRINUSE, "Address already in use"), True),
        (OSError(errno.EACCES, "Permission denied"), False),
        (RuntimeError("Failed to start: Address already in use (os error 98)"), True),
        (RuntimeError("something else entirely"), False),
        (ValueError("nope"), False),
    ],
)
def test_is_address_in_use_error(exc, expected):
    assert is_address_in_use_error(exc) is expected


class TestBindWithRetry:
    @pytest.mark.asyncio
    async def test_returns_result_on_first_success(self):
        result = await bind_with_retry(lambda: "ok", port=9000, description="test")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_awaits_awaitable_result(self):
        async def bind():
            return "async-ok"

        result = await bind_with_retry(bind, port=9000, description="test")
        assert result == "async-ok"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        attempts = {"count": 0}

        def bind():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise OSError(errno.EADDRINUSE, "Address already in use")
            return "bound"

        result = await bind_with_retry(bind, port=9000, description="test")
        assert result == "bound"
        assert attempts["count"] == 3

    @pytest.mark.asyncio
    async def test_raises_clear_error_when_permanently_in_use(self):
        def bind():
            raise OSError(errno.EADDRINUSE, "Address already in use")

        with pytest.raises(OSError) as exc_info:
            await bind_with_retry(bind, port=9123, description="My server")

        assert exc_info.value.errno == errno.EADDRINUSE
        assert "9123" in str(exc_info.value)
        assert "My server" in str(exc_info.value)
        assert "PROMETHEUS_METRICS_EXPORT_PORT" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_does_not_retry_on_unrelated_oserror(self):
        attempts = {"count": 0}

        def bind():
            attempts["count"] += 1
            raise OSError(errno.EACCES, "Permission denied")

        with pytest.raises(OSError) as exc_info:
            await bind_with_retry(bind, port=9000, description="test")

        assert exc_info.value.errno == errno.EACCES
        assert attempts["count"] == 1

    @pytest.mark.asyncio
    async def test_exhausts_configured_attempts(self, monkeypatch):
        monkeypatch.setattr(metrics_bind, "BIND_MAX_ATTEMPTS", 3)
        attempts = {"count": 0}

        def bind():
            attempts["count"] += 1
            raise OSError(errno.EADDRINUSE, "Address already in use")

        with pytest.raises(OSError):
            await bind_with_retry(bind, port=9000, description="test")

        assert attempts["count"] == 3
