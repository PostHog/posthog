import json

import pytest
from unittest.mock import AsyncMock, patch

import httpx

from posthog.temporal.delete_recordings.activities import (
    _parse_session_recording_list_response,
    bulk_delete_recordings,
    purge_deleted_metadata,
)
from posthog.temporal.delete_recordings.types import BulkDeleteInput, LoadRecordingError, PurgeDeletedMetadataInput


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_json, expected_deleted, expected_failed_count",
    [
        pytest.param(
            {"deleted": ["s1", "s2"], "failed": []},
            ["s1", "s2"],
            0,
            id="all_deleted",
        ),
        pytest.param(
            {
                "deleted": ["s1"],
                "failed": [{"session_id": "s2", "error": "Key not found"}],
            },
            ["s1"],
            1,
            id="mixed_results",
        ),
        pytest.param(
            {"deleted": [], "failed": []},
            [],
            0,
            id="empty_results",
        ),
    ],
)
async def test_bulk_delete_recordings_parses_response(response_json, expected_deleted, expected_failed_count):
    mock_response = httpx.Response(200, json=response_json, request=httpx.Request("POST", "http://test"))

    with (
        patch("posthog.temporal.delete_recordings.activities.settings") as mock_settings,
        patch("posthog.temporal.delete_recordings.activities.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = "test-secret"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await bulk_delete_recordings(BulkDeleteInput(team_id=123, session_ids=["s1", "s2"]))

    assert result.deleted == expected_deleted
    assert result.failed_count == expected_failed_count


@pytest.mark.asyncio
async def test_bulk_delete_recordings_url_construction():
    mock_response = httpx.Response(
        200,
        json={"deleted": ["s1"], "failed": []},
        request=httpx.Request("POST", "http://test"),
    )

    with (
        patch("posthog.temporal.delete_recordings.activities.settings") as mock_settings,
        patch("posthog.temporal.delete_recordings.activities.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = "test-secret"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await bulk_delete_recordings(BulkDeleteInput(team_id=456, session_ids=["s1"]))

    mock_client.post.assert_called_once_with(
        "http://recording-api:8000/api/projects/456/recordings/bulk_delete",
        json={"session_ids": ["s1"]},
    )


@pytest.mark.asyncio
async def test_bulk_delete_recordings_sends_auth_header():
    mock_response = httpx.Response(
        200,
        json={"deleted": [], "failed": []},
        request=httpx.Request("POST", "http://test"),
    )

    with (
        patch("posthog.temporal.delete_recordings.activities.settings") as mock_settings,
        patch("posthog.temporal.delete_recordings.activities.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = "my-secret-key"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await bulk_delete_recordings(BulkDeleteInput(team_id=1, session_ids=["s1"]))

    mock_client_cls.assert_called_once_with(
        timeout=60.0,
        headers={"X-Internal-Api-Secret": "my-secret-key"},
    )


@pytest.mark.asyncio
async def test_bulk_delete_recordings_no_auth_header_when_secret_empty():
    mock_response = httpx.Response(
        200,
        json={"deleted": [], "failed": []},
        request=httpx.Request("POST", "http://test"),
    )

    with (
        patch("posthog.temporal.delete_recordings.activities.settings") as mock_settings,
        patch("posthog.temporal.delete_recordings.activities.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = ""

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await bulk_delete_recordings(BulkDeleteInput(team_id=1, session_ids=["s1"]))

    mock_client_cls.assert_called_once_with(timeout=60.0, headers={})


@pytest.mark.asyncio
async def test_bulk_delete_recordings_raises_when_no_recording_api_url():
    with patch("posthog.temporal.delete_recordings.activities.settings") as mock_settings:
        mock_settings.RECORDING_API_URL = ""

        with pytest.raises(RuntimeError, match="RECORDING_API_URL is not configured"):
            await bulk_delete_recordings(BulkDeleteInput(team_id=1, session_ids=["s1"]))


@pytest.mark.asyncio
async def test_bulk_delete_recordings_raises_on_http_error():
    mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))

    with (
        patch("posthog.temporal.delete_recordings.activities.settings") as mock_settings,
        patch("posthog.temporal.delete_recordings.activities.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = ""

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await bulk_delete_recordings(BulkDeleteInput(team_id=1, session_ids=["s1"]))


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
        patch("posthog.temporal.delete_recordings.activities.get_client", return_value=mock_client),
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
