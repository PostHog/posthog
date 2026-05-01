from unittest.mock import MagicMock, patch

from django.db import OperationalError

from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker import (
    MAX_RETRIES_DEFAULT,
    MAX_RETRIES_TRANSIENT,
    RETRY_TTL_SECONDS,
    RetryExhaustedError,
    RetryInfo,
    classify_error,
    clear_retry_info,
    get_retry_info,
    get_retry_key,
    increment_retry_count,
    is_retry_exhausted,
    update_retry_error_type,
)


class TestRetryInfo:
    def test_to_json_roundtrip(self):
        info = RetryInfo(count=3, error_type="transient", last_error="connection refused")
        result = RetryInfo.from_json(info.to_json())

        assert result.count == 3
        assert result.error_type == "transient"
        assert result.last_error == "connection refused"

    def test_to_json_roundtrip_defaults(self):
        info = RetryInfo()
        result = RetryInfo.from_json(info.to_json())

        assert result.count == 0
        assert result.error_type is None
        assert result.last_error is None

    def test_defaults(self):
        info = RetryInfo()
        assert info.count == 0
        assert info.error_type is None
        assert info.last_error is None


class TestRetryExhaustedError:
    def test_message_contains_details(self):
        info = RetryInfo(count=3, error_type="non_transient", last_error="ValueError: bad data")
        error = RetryExhaustedError(info)

        assert "3 attempts" in str(error)
        assert "non_transient" in str(error)
        assert "ValueError: bad data" in str(error)
        assert error.retry_info is info


class TestGetRetryKey:
    def test_key_format(self):
        key = get_retry_key(team_id=1, schema_id="abc", run_uuid="run-1", batch_index=5)
        assert key == "warehouse_pipelines:retry:1:abc:run-1:5"


class TestGetRetryInfo:
    def test_returns_default_when_key_missing(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = get_retry_info(1, "schema", "run", 0)

        assert result.count == 0
        assert result.error_type is None

    def test_returns_default_when_redis_unavailable(self):
        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = get_retry_info(1, "schema", "run", 0)

        assert result.count == 0

    def test_returns_stored_info(self):
        stored = RetryInfo(count=2, error_type="transient", last_error="timeout")
        mock_redis = MagicMock()
        mock_redis.get.return_value = stored.to_json()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = get_retry_info(1, "schema", "run", 0)

        assert result.count == 2
        assert result.error_type == "transient"
        assert result.last_error == "timeout"


class TestIncrementRetryCount:
    def test_increments_from_zero(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = increment_retry_count(1, "schema", "run", 0)

        assert result.count == 1
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[1]["ex"] == RETRY_TTL_SECONDS

    def test_increments_existing(self):
        existing = RetryInfo(count=2, error_type="transient", last_error="timeout")
        mock_redis = MagicMock()
        mock_redis.get.return_value = existing.to_json()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = increment_retry_count(1, "schema", "run", 0)

        assert result.count == 3
        assert result.error_type == "transient"

    def test_returns_default_when_redis_unavailable(self):
        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = increment_retry_count(1, "schema", "run", 0)

        assert result.count == 0


class TestUpdateRetryErrorType:
    def test_updates_error_type_and_last_error(self):
        existing = RetryInfo(count=2, error_type=None, last_error=None)
        mock_redis = MagicMock()
        mock_redis.get.return_value = existing.to_json()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            update_retry_error_type(1, "schema", "run", 0, error_type="non_transient", last_error="ValueError")

        saved = RetryInfo.from_json(mock_redis.set.call_args[0][1])
        assert saved.count == 2  # count unchanged
        assert saved.error_type == "non_transient"
        assert saved.last_error == "ValueError"

    def test_truncates_long_error(self):
        existing = RetryInfo(count=1)
        mock_redis = MagicMock()
        mock_redis.get.return_value = existing.to_json()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            long_error = "x" * 2000
            update_retry_error_type(1, "schema", "run", 0, error_type="transient", last_error=long_error)

        saved = RetryInfo.from_json(mock_redis.set.call_args[0][1])
        assert saved.last_error is not None
        assert len(saved.last_error) == 1000

    def test_creates_entry_when_key_missing(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            update_retry_error_type(1, "schema", "run", 0, error_type="transient", last_error="err")

        mock_redis.set.assert_called_once()
        saved = RetryInfo.from_json(mock_redis.set.call_args[0][1])
        assert saved.count == 0
        assert saved.error_type == "transient"
        assert saved.last_error == "err"


class TestClearRetryInfo:
    def test_deletes_key(self):
        mock_redis = MagicMock()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker.get_redis_client"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            clear_retry_info(1, "schema", "run", 0)

        mock_redis.delete.assert_called_once_with("warehouse_pipelines:retry:1:schema:run:0")


class TestIsRetryExhausted:
    @parameterized.expand(
        [
            ("transient_below_limit", RetryInfo(count=MAX_RETRIES_TRANSIENT, error_type="transient"), False),
            ("transient_at_limit", RetryInfo(count=MAX_RETRIES_TRANSIENT + 1, error_type="transient"), True),
            ("non_transient_below_limit", RetryInfo(count=MAX_RETRIES_DEFAULT, error_type="non_transient"), False),
            ("non_transient_at_limit", RetryInfo(count=MAX_RETRIES_DEFAULT + 1, error_type="non_transient"), True),
            ("none_below_limit", RetryInfo(count=MAX_RETRIES_DEFAULT, error_type=None), False),
            ("none_at_limit", RetryInfo(count=MAX_RETRIES_DEFAULT + 1, error_type=None), True),
        ]
    )
    def test_exhaustion_thresholds(self, _name, retry_info, expected):
        assert is_retry_exhausted(retry_info) == expected


class TestClassifyError:
    @parameterized.expand(
        [
            ("operational_error", OperationalError("connection refused"), "transient"),
            ("connection_error", ConnectionError("reset"), "transient"),
            ("timeout_error", TimeoutError("timed out"), "transient"),
            ("os_error", OSError("network unreachable"), "transient"),
            ("value_error", ValueError("bad data"), "non_transient"),
            ("type_error", TypeError("wrong type"), "non_transient"),
            ("runtime_error", RuntimeError("unexpected"), "non_transient"),
        ]
    )
    def test_classification(self, _name, error, expected):
        assert classify_error(error) == expected
