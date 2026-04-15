import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import (
    get_idempotency_key,
    is_batch_already_processed,
    mark_batch_as_processed,
)


class TestGetIdempotencyKey:
    def test_key_format(self):
        key = get_idempotency_key(team_id=1, schema_id="schema-abc", run_uuid="run-123", batch_index=5)
        assert key == "warehouse_pipelines:processed:1:schema-abc:run-123:5"


class TestIsBatchAlreadyProcessed:
    def test_returns_true_when_redis_flag_set(self):
        redis_client = MagicMock()
        redis_client.exists = MagicMock(return_value=1)

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            result = is_batch_already_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)

        assert result is True
        redis_client.exists.assert_called_once_with("warehouse_pipelines:processed:1:s:r:0")

    def test_returns_false_when_redis_flag_missing_and_no_helper(self):
        redis_client = MagicMock()
        redis_client.exists = MagicMock(return_value=0)

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            result = is_batch_already_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)

        assert result is False

    def test_skips_delta_fallback_when_redis_client_unavailable_and_no_helper(self):
        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = None
            result = is_batch_already_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)

        assert result is False

    def test_returns_true_when_delta_history_matches_after_redis_miss(self):
        redis_client = MagicMock()
        redis_client.exists = MagicMock(return_value=0)

        helper = MagicMock()
        helper.has_batch_been_committed = AsyncMock(return_value=True)

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            result = is_batch_already_processed(
                team_id=1,
                schema_id="s",
                run_uuid="run-abc",
                batch_index=3,
                delta_table_helper=helper,
            )

        assert result is True
        helper.has_batch_been_committed.assert_called_once_with("run-abc", 3)

    def test_returns_false_when_both_redis_and_delta_history_miss(self):
        redis_client = MagicMock()
        redis_client.exists = MagicMock(return_value=0)

        helper = MagicMock()
        helper.has_batch_been_committed = AsyncMock(return_value=False)

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            result = is_batch_already_processed(
                team_id=1, schema_id="s", run_uuid="r", batch_index=0, delta_table_helper=helper
            )

        assert result is False

    def test_redis_hit_short_circuits_delta_fallback(self):
        redis_client = MagicMock()
        redis_client.exists = MagicMock(return_value=1)

        helper = MagicMock()
        helper.has_batch_been_committed = AsyncMock(return_value=False)

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            result = is_batch_already_processed(
                team_id=1, schema_id="s", run_uuid="r", batch_index=0, delta_table_helper=helper
            )

        assert result is True
        helper.has_batch_been_committed.assert_not_called()

    def test_propagates_errors_from_delta_fallback(self):
        """If the delta history check errors, we must not fail open — doing so would
        re-enable the duplicate-write race the fallback is supposed to fix. The error
        is surfaced so Kafka can redeliver later."""
        redis_client = MagicMock()
        redis_client.exists = MagicMock(return_value=0)

        helper = MagicMock()
        helper.has_batch_been_committed = AsyncMock(side_effect=RuntimeError("delta blew up"))

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            with pytest.raises(RuntimeError, match="delta blew up"):
                is_batch_already_processed(
                    team_id=1, schema_id="s", run_uuid="r", batch_index=0, delta_table_helper=helper
                )


class TestMarkBatchAsProcessed:
    def test_sets_key_with_ttl(self):
        redis_client = MagicMock()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            mark_batch_as_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)

        redis_client.set.assert_called_once_with("warehouse_pipelines:processed:1:s:r:0", "1", ex=72 * 60 * 60)

    def test_noop_when_redis_client_unavailable(self):
        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"
        ) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = None
            mark_batch_as_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)
            # No exception — the function logs a warning and returns
