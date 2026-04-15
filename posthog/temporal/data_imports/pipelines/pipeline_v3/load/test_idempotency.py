import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import (
    get_idempotency_key,
    is_batch_already_processed,
    mark_batch_as_processed,
)

REDIS_CLIENT_PATH = "posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency.get_redis_client"


def _redis_client(exists_value: int | None) -> MagicMock | None:
    """Build a MagicMock Redis client whose `exists` returns `exists_value`.

    `exists_value=None` represents the "Redis unavailable" case (the contextmanager
    yields `None`).
    """
    if exists_value is None:
        return None
    client = MagicMock()
    client.exists = MagicMock(return_value=exists_value)
    return client


def _delta_helper(committed: bool | Exception | None) -> MagicMock | None:
    """Build a `DeltaTableHelper`-shaped mock.

    - `True`  → `has_batch_been_committed` returns True
    - `False` → returns False
    - Exception instance → raises that exception
    - `None`  → no helper (caller passes None)
    """
    if committed is None:
        return None
    helper = MagicMock()
    if isinstance(committed, Exception):
        helper.has_batch_been_committed = AsyncMock(side_effect=committed)
    else:
        helper.has_batch_been_committed = AsyncMock(return_value=committed)
    return helper


class TestGetIdempotencyKey:
    def test_key_format(self):
        key = get_idempotency_key(team_id=1, schema_id="schema-abc", run_uuid="run-123", batch_index=5)
        assert key == "warehouse_pipelines:processed:1:schema-abc:run-123:5"


class TestIsBatchAlreadyProcessed:
    @parameterized.expand(
        [
            # (name, redis_exists, helper_state, expected_result)
            ("redis_hit_no_helper", 1, None, True),
            ("redis_hit_short_circuits_helper", 1, False, True),
            ("redis_miss_no_helper", 0, None, False),
            ("redis_miss_helper_hit", 0, True, True),
            ("redis_miss_helper_miss", 0, False, False),
            ("redis_unavailable_no_helper", None, None, False),
            ("redis_unavailable_helper_hit", None, True, True),
        ]
    )
    def test_decision_matrix(
        self,
        _name: str,
        redis_exists: int | None,
        helper_state: bool | None,
        expected_result: bool,
    ):
        client = _redis_client(redis_exists)
        helper = _delta_helper(helper_state)

        with patch(REDIS_CLIENT_PATH) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = client
            result = is_batch_already_processed(
                team_id=1,
                schema_id="s",
                run_uuid="r",
                batch_index=0,
                delta_table_helper=helper,
            )

        assert result is expected_result

    def test_redis_hit_uses_correct_key(self):
        client = _redis_client(1)
        with patch(REDIS_CLIENT_PATH) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = client
            is_batch_already_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)

        assert client is not None  # for mypy
        client.exists.assert_called_once_with("warehouse_pipelines:processed:1:s:r:0")

    def test_redis_hit_short_circuits_delta_helper_call(self):
        client = _redis_client(1)
        helper = _delta_helper(False)

        with patch(REDIS_CLIENT_PATH) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = client
            is_batch_already_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0, delta_table_helper=helper)

        assert helper is not None  # for mypy
        helper.has_batch_been_committed.assert_not_called()

    def test_helper_called_with_run_uuid_and_batch_index(self):
        client = _redis_client(0)
        helper = _delta_helper(True)

        with patch(REDIS_CLIENT_PATH) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = client
            is_batch_already_processed(
                team_id=1,
                schema_id="s",
                run_uuid="run-abc",
                batch_index=3,
                delta_table_helper=helper,
            )

        assert helper is not None
        helper.has_batch_been_committed.assert_called_once_with("run-abc", 3)

    def test_propagates_errors_from_delta_fallback(self):
        """If the delta history check errors, we must not fail open — doing so would
        re-enable the duplicate-write race the fallback is supposed to fix. The error
        is surfaced so Kafka can redeliver later."""
        client = _redis_client(0)
        helper = _delta_helper(RuntimeError("delta blew up"))

        with patch(REDIS_CLIENT_PATH) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = client
            with pytest.raises(RuntimeError, match="delta blew up"):
                is_batch_already_processed(
                    team_id=1, schema_id="s", run_uuid="r", batch_index=0, delta_table_helper=helper
                )


class TestMarkBatchAsProcessed:
    def test_sets_key_with_ttl(self):
        redis_client = MagicMock()

        with patch(REDIS_CLIENT_PATH) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = redis_client
            mark_batch_as_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)

        redis_client.set.assert_called_once_with("warehouse_pipelines:processed:1:s:r:0", "1", ex=72 * 60 * 60)

    def test_noop_when_redis_client_unavailable(self):
        with patch(REDIS_CLIENT_PATH) as mock_get_client:
            mock_get_client.return_value.__enter__.return_value = None
            mark_batch_as_processed(team_id=1, schema_id="s", run_uuid="r", batch_index=0)
            # No exception — the function logs a warning and returns
