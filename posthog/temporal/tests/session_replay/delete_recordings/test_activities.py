import json

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.exceptions import ApplicationError

from posthog.temporal.session_replay.delete_recordings.activities import (
    _parse_session_recording_list_response,
    delete_recordings,
    purge_deleted_metadata,
)
from posthog.temporal.session_replay.delete_recordings.types import (
    DeleteRecordingsInput,
    LoadRecordingError,
    PurgeDeletedMetadataInput,
)


def _patch_recording_api_client(failed_ids):
    mock_client = AsyncMock()
    mock_client.delete_recordings.return_value = failed_ids
    mock_client_cm = AsyncMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)
    return patch(
        "posthog.temporal.session_replay.delete_recordings.activities.recording_api_client",
        return_value=mock_client_cm,
    ), mock_client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed_ids, expected_deleted, expected_failed_count",
    [
        pytest.param([], ["s1", "s2"], 0, id="all_deleted"),
        pytest.param(["s2"], ["s1"], 1, id="mixed_results"),
        pytest.param(["s1", "s2"], [], 2, id="all_failed"),
    ],
)
async def test_delete_recordings_computes_deleted_and_failed(failed_ids, expected_deleted, expected_failed_count):
    patcher, mock_client = _patch_recording_api_client(failed_ids)

    with patcher:
        result = await delete_recordings(
            DeleteRecordingsInput(team_id=123, session_ids=["s1", "s2"], deleted_by="test@example.com")
        )

    mock_client.delete_recordings.assert_called_once_with(["s1", "s2"], 123, "test@example.com")
    assert result.deleted == expected_deleted
    assert result.failed_count == expected_failed_count


@pytest.mark.asyncio
async def test_delete_recordings_raises_non_retryable_when_no_recording_api_url():
    with patch(
        "posthog.temporal.session_replay.delete_recordings.activities.recording_api_client",
        side_effect=RuntimeError("RECORDING_API_URL is not configured"),
    ):
        with pytest.raises(ApplicationError) as exc_info:
            await delete_recordings(DeleteRecordingsInput(team_id=1, session_ids=["s1"], deleted_by="test@posthog.com"))

    assert exc_info.value.non_retryable is True
    assert "RECORDING_API_URL is not configured" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grace_period_days",
    [
        pytest.param(1, id="minimum"),
        pytest.param(10, id="default"),
        pytest.param(30, id="monthly"),
        pytest.param(365, id="maximum"),
    ],
)
async def test_purge_deleted_metadata_parameterizes_grace_period(grace_period_days):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("posthog.temporal.session_replay.delete_recordings.activities.get_client", return_value=mock_client),
        patch("posthog.settings.data_stores.CLICKHOUSE_CLUSTER", "posthog"),
    ):
        result = await purge_deleted_metadata(PurgeDeletedMetadataInput(grace_period_days=grace_period_days))

    mock_client.execute_query.assert_called_once()
    call_kwargs = mock_client.execute_query.call_args
    assert call_kwargs.kwargs["query_parameters"] == {"grace_period_days": grace_period_days}
    assert "{grace_period_days:Int32}" in call_kwargs.args[0]
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.completed_at >= result.started_at


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_days",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(366, id="over_max"),
    ],
)
async def test_purge_deleted_metadata_rejects_invalid_grace_period(invalid_days):
    with pytest.raises(ValueError, match="grace_period_days must be between 1 and 365"):
        await purge_deleted_metadata(PurgeDeletedMetadataInput(grace_period_days=invalid_days))


@pytest.mark.parametrize(
    "raw_response, expected",
    [
        pytest.param(
            json.dumps({"data": [{"session_id": "s1"}, {"session_id": "s2"}]}).encode(),
            ["s1", "s2"],
            id="valid_response",
        ),
        pytest.param(
            json.dumps({"data": []}).encode(),
            [],
            id="empty_data",
        ),
    ],
)
def test_parse_session_recording_list_response(raw_response, expected):
    assert _parse_session_recording_list_response(raw_response) == expected


@pytest.mark.parametrize(
    "raw_response, error_match",
    [
        pytest.param(b"", "Got empty response", id="empty_bytes"),
        pytest.param(b"not json", "Unable to parse JSON", id="malformed_json"),
        pytest.param(json.dumps({"rows": []}).encode(), "Got malformed JSON", id="missing_data_key"),
    ],
)
def test_parse_session_recording_list_response_errors(raw_response, error_match):
    with pytest.raises(LoadRecordingError, match=error_match):
        _parse_session_recording_list_response(raw_response)
