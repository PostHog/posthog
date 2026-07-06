from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.external_data_job import Any_Source_Errors
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.common import webhook_s3
from posthog.temporal.data_imports.sources.common.webhook_s3 import WEBHOOK_DELIVERY_FAILING_ERROR, WebhookSourceManager
from posthog.temporal.data_imports.util import NonRetryableException


def _build_manager() -> WebhookSourceManager:
    logger = Mock()
    logger.adebug = AsyncMock()
    logger.awarning = AsyncMock()
    inputs = SourceInputs(
        schema_name="charges",
        schema_id="11111111-1111-1111-1111-111111111111",
        source_id="22222222-2222-2222-2222-222222222222",
        team_id=1,
        should_use_incremental_field=True,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="33333333-3333-3333-3333-333333333333",
        logger=logger,
        reset_pipeline=False,
    )
    return WebhookSourceManager(inputs, logger)


class TestClassifyWebhookFailure:
    @parameterized.expand(
        [
            # name, rows (newest-first: (http_status, ok, reason)), expected reason
            ("empty", [], None),
            (
                "three_consecutive_400s_fails",
                [(400, 0, "Bad signature"), (400, 0, "Bad signature"), (400, 0, "Bad signature")],
                "Bad signature",
            ),
            ("two_400s_below_threshold", [(400, 0, "Bad signature"), (400, 0, "Bad signature")], None),
            (
                "latest_success_recovers",
                [(200, 1, ""), (400, 0, "Bad signature"), (400, 0, "Bad signature"), (400, 0, "Bad signature")],
                None,
            ),
            (
                "transient_5xx_breaks_streak",
                [(400, 0, "Bad signature"), (400, 0, "Bad signature"), (500, 0, "")],
                None,
            ),
            (
                "401_and_403_count",
                [(401, 0, "Unauthorized"), (403, 0, "Forbidden"), (401, 0, "Unauthorized")],
                "Unauthorized",
            ),
            ("head_429_ignored", [(429, 0, "Disabled"), (400, 0, "x"), (400, 0, "x"), (400, 0, "x")], None),
            ("head_404_ignored", [(404, 0, "Not found"), (400, 0, "x"), (400, 0, "x"), (400, 0, "x")], None),
            (
                "empty_reason_falls_back_to_status",
                [(400, 0, ""), (400, 0, ""), (400, 0, "")],
                "HTTP 400",
            ),
            (
                "more_than_three_failures",
                [(403, 0, "Forbidden")] * 5,
                "Forbidden",
            ),
        ]
    )
    def test_classify(self, _name, rows, expected):
        assert WebhookSourceManager._classify_webhook_failure(rows) == expected


class TestWebhookFailureLookbackSeconds:
    @parameterized.expand(
        [
            # interval, expected total seconds (interval + max(interval*0.2, 5min))
            ("default_when_none", None, int((timedelta(hours=6) + timedelta(hours=6) * 0.2).total_seconds())),
            ("small_interval_uses_min_buffer", timedelta(minutes=5), int((timedelta(minutes=10)).total_seconds())),
            (
                "hourly_uses_proportional_buffer",
                timedelta(hours=1),
                int((timedelta(hours=1, minutes=12)).total_seconds()),
            ),
            ("daily", timedelta(days=1), int((timedelta(days=1) + timedelta(days=1) * 0.2).total_seconds())),
        ]
    )
    async def test_lookback(self, _name, interval, expected_seconds):
        manager = _build_manager()
        schema = Mock(sync_frequency_interval=interval)
        with patch.object(webhook_s3, "database_sync_to_async_pool", lambda fn: AsyncMock(return_value=schema)):
            assert await manager._webhook_failure_lookback_seconds() == expected_seconds


class TestRaiseOnPersistentWebhookFailure:
    async def test_raises_non_retryable_on_persistent_failure(self):
        manager = _build_manager()
        rows = [(400, 0, "Bad signature")] * 3
        with (
            patch.object(manager, "_webhook_failure_lookback_seconds", AsyncMock(return_value=3600)),
            patch.object(webhook_s3, "sync_execute", return_value=rows),
        ):
            with pytest.raises(NonRetryableException) as exc:
                await manager._raise_on_persistent_webhook_failure()

        assert WEBHOOK_DELIVERY_FAILING_ERROR in str(exc.value)
        assert "Bad signature" in str(exc.value)

    async def test_does_not_raise_when_healthy(self):
        manager = _build_manager()
        rows = [(200, 1, "")]
        with (
            patch.object(manager, "_webhook_failure_lookback_seconds", AsyncMock(return_value=3600)),
            patch.object(webhook_s3, "sync_execute", return_value=rows),
        ):
            await manager._raise_on_persistent_webhook_failure()

    async def test_get_items_raises_before_reading_s3(self):
        manager = _build_manager()
        with (
            patch.object(manager, "_persistent_webhook_failure_reason", AsyncMock(return_value="Bad signature")),
            patch.object(manager, "_list_webhook_parquet_files", AsyncMock()) as list_files,
        ):
            with pytest.raises(NonRetryableException):
                async for _ in manager.get_items():
                    pass

        list_files.assert_not_called()

    def test_raised_phrase_is_registered_as_non_retryable(self):
        # Drift guard: the leading phrase of the raised message must remain a key
        # in Any_Source_Errors, otherwise the run would not be classified non-retryable.
        assert WEBHOOK_DELIVERY_FAILING_ERROR in Any_Source_Errors
