import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    LOCK_TTL_SECONDS,
    _lock_key,
    acquire_v3_pipeline_lock,
    release_v3_pipeline_lock,
)


class TestLockKey:
    def test_format(self) -> None:
        assert _lock_key(1, "schema-abc") == "v3_pipeline_lock:1:schema-abc"


class TestAcquireV3PipelineLock:
    @pytest.mark.parametrize(
        "set_return, expected",
        [
            (True, True),
            (None, False),
        ],
        ids=["acquired", "already_held"],
    )
    @patch("posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_acquire_result(self, mock_ctx: MagicMock, set_return: bool | None, expected: bool) -> None:
        mock_redis = MagicMock()
        mock_redis.set.return_value = set_return
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = acquire_v3_pipeline_lock(1, "s-1", "tok-1")
        assert result is expected
        mock_redis.set.assert_called_once_with(_lock_key(1, "s-1"), "tok-1", nx=True, ex=LOCK_TTL_SECONDS)

    @patch("posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_fail_open_on_redis_unavailable(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert acquire_v3_pipeline_lock(1, "s-1", "tok-1") is True

    @patch("posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_fail_open_on_set_exception(self, mock_ctx: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.set.side_effect = Exception("connection lost")
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert acquire_v3_pipeline_lock(1, "s-1", "tok-1") is True


class TestReleaseV3PipelineLock:
    @pytest.mark.parametrize(
        "eval_return, expected",
        [
            (1, True),
            (0, False),
        ],
        ids=["released", "token_mismatch"],
    )
    @patch("posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_release_result(self, mock_ctx: MagicMock, eval_return: int, expected: bool) -> None:
        mock_redis = MagicMock()
        mock_redis.eval.return_value = eval_return
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = release_v3_pipeline_lock(1, "s-1", "tok-1")
        assert result is expected

    @patch("posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_returns_false_on_redis_unavailable(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert release_v3_pipeline_lock(1, "s-1", "tok-1") is False

    @patch("posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_returns_false_on_eval_exception(self, mock_ctx: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.eval.side_effect = Exception("connection lost")
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert release_v3_pipeline_lock(1, "s-1", "tok-1") is False
