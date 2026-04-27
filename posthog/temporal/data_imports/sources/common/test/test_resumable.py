import dataclasses

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class _FakeResumeState:
    cursor: str


def _make_inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="schema",
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def _make_manager() -> ResumableSourceManager[_FakeResumeState]:
    return ResumableSourceManager(_make_inputs(), _FakeResumeState)


@override_settings(DATA_WAREHOUSE_REDIS_HOST="redis-host", DATA_WAREHOUSE_REDIS_PORT="6379")
def test_save_state_swallows_redis_connection_error() -> None:
    manager = _make_manager()

    with (
        patch(
            "posthog.temporal.data_imports.sources.common.resumable.get_client",
            side_effect=ConnectionError("nope"),
        ),
        patch("posthog.temporal.data_imports.sources.common.resumable.capture_exception") as mock_capture,
    ):
        manager.save_state(_FakeResumeState(cursor="abc"))

    assert mock_capture.call_count == 1


@override_settings(DATA_WAREHOUSE_REDIS_HOST="redis-host", DATA_WAREHOUSE_REDIS_PORT="6379")
def test_can_resume_returns_false_on_redis_failure() -> None:
    manager = _make_manager()

    with (
        patch(
            "posthog.temporal.data_imports.sources.common.resumable.get_client",
            side_effect=ConnectionError("nope"),
        ),
        patch("posthog.temporal.data_imports.sources.common.resumable.capture_exception") as mock_capture,
    ):
        result = manager.can_resume()

    assert result is False
    assert mock_capture.call_count == 1


@override_settings(DATA_WAREHOUSE_REDIS_HOST="redis-host", DATA_WAREHOUSE_REDIS_PORT="6379")
def test_load_state_returns_none_on_redis_failure() -> None:
    manager = _make_manager()

    with (
        patch(
            "posthog.temporal.data_imports.sources.common.resumable.get_client",
            side_effect=ConnectionError("nope"),
        ),
        patch("posthog.temporal.data_imports.sources.common.resumable.capture_exception") as mock_capture,
    ):
        result = manager.load_state()

    assert result is None
    assert mock_capture.call_count == 1


@override_settings(DATA_WAREHOUSE_REDIS_HOST="redis-host", DATA_WAREHOUSE_REDIS_PORT="6379")
def test_save_state_swallows_ping_failure() -> None:
    manager = _make_manager()
    redis_client = MagicMock()
    redis_client.ping.side_effect = ConnectionError("ping failed")

    with (
        patch(
            "posthog.temporal.data_imports.sources.common.resumable.get_client",
            return_value=redis_client,
        ),
        patch("posthog.temporal.data_imports.sources.common.resumable.capture_exception") as mock_capture,
    ):
        manager.save_state(_FakeResumeState(cursor="abc"))

    assert mock_capture.call_count == 1
    redis_client.set.assert_not_called()


@pytest.mark.parametrize("host,port", [("", "6379"), ("redis-host", "")])
def test_missing_env_vars_swallowed(host: str, port: str) -> None:
    manager = _make_manager()

    with (
        override_settings(DATA_WAREHOUSE_REDIS_HOST=host, DATA_WAREHOUSE_REDIS_PORT=port),
        patch("posthog.temporal.data_imports.sources.common.resumable.capture_exception") as mock_capture,
    ):
        assert manager.can_resume() is False
        assert manager.load_state() is None
        manager.save_state(_FakeResumeState(cursor="abc"))

    assert mock_capture.call_count == 3


@override_settings(DATA_WAREHOUSE_REDIS_HOST="redis-host", DATA_WAREHOUSE_REDIS_PORT="6379")
def test_save_state_writes_to_redis() -> None:
    manager = _make_manager()
    redis_client = MagicMock()

    with patch(
        "posthog.temporal.data_imports.sources.common.resumable.get_client",
        return_value=redis_client,
    ):
        manager.save_state(_FakeResumeState(cursor="abc"))

    redis_client.ping.assert_called_once()
    redis_client.set.assert_called_once()
    args, kwargs = redis_client.set.call_args
    assert args[0] == "posthog:data_warehouse:resumable_source:1:job-id"
    assert '"cursor":"abc"' in args[1] or '"cursor": "abc"' in args[1]
    assert kwargs.get("ex") == 60 * 60 * 24


@override_settings(DATA_WAREHOUSE_REDIS_HOST="redis-host", DATA_WAREHOUSE_REDIS_PORT="6379")
def test_can_resume_returns_true_when_key_exists() -> None:
    manager = _make_manager()
    redis_client = MagicMock()
    redis_client.exists.return_value = 1

    with patch(
        "posthog.temporal.data_imports.sources.common.resumable.get_client",
        return_value=redis_client,
    ):
        assert manager.can_resume() is True


@override_settings(DATA_WAREHOUSE_REDIS_HOST="redis-host", DATA_WAREHOUSE_REDIS_PORT="6379")
def test_load_state_round_trips() -> None:
    manager = _make_manager()
    redis_client = MagicMock()
    redis_client.get.return_value = b'{"cursor":"abc"}'

    with patch(
        "posthog.temporal.data_imports.sources.common.resumable.get_client",
        return_value=redis_client,
    ):
        result = manager.load_state()

    assert result == _FakeResumeState(cursor="abc")
