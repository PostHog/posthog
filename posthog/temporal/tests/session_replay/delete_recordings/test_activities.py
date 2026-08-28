import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import httpx

from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.temporal.session_replay.delete_recordings.activities import (
    PURGE_DELETE_BATCH_SIZE,
    _parse_session_recording_list_response,
    delete_recordings,
    delete_team_metadata,
    purge_deleted_metadata,
)
from posthog.temporal.session_replay.delete_recordings.types import (
    DeleteRecordingsInput,
    DeleteTeamMetadataInput,
    LoadRecordingError,
    PurgeDeletedMetadataInput,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_json, expected_deleted, expected_failed_count",
    [
        pytest.param(
            [
                {"sessionId": "s1", "ok": True, "status": "deleted", "deletedAt": 1700000000},
                {"sessionId": "s2", "ok": True, "status": "deleted", "deletedAt": 1700000000},
            ],
            ["s1", "s2"],
            0,
            id="all_deleted",
        ),
        pytest.param(
            [
                {"sessionId": "s1", "ok": True, "status": "deleted", "deletedAt": 1700000000},
                {"sessionId": "s2", "ok": False, "error": "shred_failed"},
            ],
            ["s1"],
            1,
            id="mixed_results",
        ),
        pytest.param(
            [],
            [],
            0,
            id="empty_results",
        ),
    ],
)
async def test_delete_recordings_parses_response(response_json, expected_deleted, expected_failed_count):
    mock_response = httpx.Response(200, json=response_json, request=httpx.Request("POST", "http://test"))

    with (
        patch("posthog.temporal.session_replay.delete_recordings.activities.settings") as mock_settings,
        patch(
            "posthog.temporal.session_replay.delete_recordings.activities.internal_httpx_async_client"
        ) as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = "test-secret"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await delete_recordings(
            DeleteRecordingsInput(team_id=123, session_ids=["s1", "s2"], deleted_by="test@example.com")
        )

    assert result.deleted == expected_deleted
    assert result.failed_count == expected_failed_count


@pytest.mark.asyncio
async def test_delete_recordings_url_construction():
    mock_response = httpx.Response(
        200,
        json=[{"sessionId": "s1", "ok": True, "status": "deleted", "deletedAt": 1700000000}],
        request=httpx.Request("POST", "http://test"),
    )

    with (
        patch("posthog.temporal.session_replay.delete_recordings.activities.settings") as mock_settings,
        patch(
            "posthog.temporal.session_replay.delete_recordings.activities.internal_httpx_async_client"
        ) as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = "test-secret"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await delete_recordings(DeleteRecordingsInput(team_id=456, session_ids=["s1"], deleted_by="test@posthog.com"))

    mock_client.post.assert_called_once_with(
        "http://recording-api:8000/api/projects/456/recordings/delete",
        json={"session_ids": ["s1"], "deleted_by": "test@posthog.com"},
    )


def _mock_delete_response_client(mock_client_cls):
    mock_client = AsyncMock()
    mock_client.post.return_value = httpx.Response(200, json=[], request=httpx.Request("POST", "http://test"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "internal_secret, jwt_secret, expected_headers",
    [
        pytest.param("my-secret-key", "", {"X-Internal-Api-Secret"}, id="legacy_secret_only"),
        pytest.param("", "signing-key", {"Authorization"}, id="jwt_only"),
        pytest.param(
            "my-secret-key",
            "signing-key",
            {"X-Internal-Api-Secret", "Authorization"},
            id="both_during_rollout",
        ),
        pytest.param("", "", set(), id="nothing_configured"),
    ],
)
async def test_delete_recordings_auth_headers(internal_secret, jwt_secret, expected_headers):
    with (
        override_settings(
            RECORDING_API_URL="http://recording-api:8000",
            INTERNAL_API_SECRET=internal_secret,
            RECORDING_API_JWT_SECRET=jwt_secret,
        ),
        patch(
            "posthog.temporal.session_replay.delete_recordings.activities.internal_httpx_async_client"
        ) as mock_client_cls,
    ):
        _mock_delete_response_client(mock_client_cls)

        await delete_recordings(DeleteRecordingsInput(team_id=1, session_ids=["s1"], deleted_by="test@posthog.com"))

    mock_client_cls.assert_called_once()
    headers = mock_client_cls.call_args.kwargs["headers"]
    assert set(headers) == expected_headers
    if "X-Internal-Api-Secret" in expected_headers:
        assert headers["X-Internal-Api-Secret"] == internal_secret


@pytest.mark.asyncio
async def test_delete_recordings_token_is_scoped_to_team_and_delete_op():
    with (
        override_settings(
            RECORDING_API_URL="http://recording-api:8000",
            INTERNAL_API_SECRET="",
            RECORDING_API_JWT_SECRET="signing-key",
        ),
        patch(
            "posthog.temporal.session_replay.delete_recordings.activities.internal_httpx_async_client"
        ) as mock_client_cls,
    ):
        _mock_delete_response_client(mock_client_cls)

        await delete_recordings(DeleteRecordingsInput(team_id=456, session_ids=["s1"], deleted_by="test@posthog.com"))

    token = mock_client_cls.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
    claims = decode_jwt(token, PosthogJwtAudience.RECORDING_API, verification_keys=["signing-key"])
    assert claims["team_id"] == 456
    assert claims["op"] == "delete"


@pytest.mark.asyncio
async def test_delete_recordings_raises_when_no_recording_api_url():
    with patch("posthog.temporal.session_replay.delete_recordings.activities.settings") as mock_settings:
        mock_settings.RECORDING_API_URL = ""

        with pytest.raises(RuntimeError, match="RECORDING_API_URL is not configured"):
            await delete_recordings(DeleteRecordingsInput(team_id=1, session_ids=["s1"], deleted_by="test@posthog.com"))


@pytest.mark.asyncio
async def test_delete_recordings_raises_on_http_error():
    mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))

    with (
        patch("posthog.temporal.session_replay.delete_recordings.activities.settings") as mock_settings,
        patch(
            "posthog.temporal.session_replay.delete_recordings.activities.internal_httpx_async_client"
        ) as mock_client_cls,
    ):
        mock_settings.RECORDING_API_URL = "http://recording-api:8000"
        mock_settings.INTERNAL_API_SECRET = ""

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await delete_recordings(DeleteRecordingsInput(team_id=1, session_ids=["s1"], deleted_by="test@posthog.com"))


def _mock_clickhouse_client(marker_rows: list[dict]) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    response = MagicMock()
    response.content.read = AsyncMock(return_value=json.dumps({"data": marker_rows}).encode())
    aget_query_ctx = MagicMock()
    aget_query_ctx.__aenter__ = AsyncMock(return_value=response)
    aget_query_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_client.aget_query = MagicMock(return_value=aget_query_ctx)

    return mock_client


@pytest.mark.asyncio
async def test_purge_deleted_metadata_deletes_marked_sessions_by_pair():
    """The purge must delete the marked sessions' rows by (team_id, session_id).

    A `WHERE is_deleted = 1` predicate only ever matches the marker row: the marker is
    stamped with the deletion time, so it never merges with the recording's real rows.
    """
    marker_rows = [
        {"team_id": "1", "session_id": "s1"},
        {"team_id": "1", "session_id": "s2"},
        {"team_id": "2", "session_id": "s3"},
    ]
    mock_client = _mock_clickhouse_client(marker_rows)

    with patch("posthog.temporal.session_replay.delete_recordings.activities.get_client", return_value=mock_client):
        result = await purge_deleted_metadata(PurgeDeletedMetadataInput(grace_period_days=10))

    select_kwargs = mock_client.aget_query.call_args.kwargs
    assert select_kwargs["query_parameters"]["grace_period_days"] == 10

    assert mock_client.execute_query.call_count == 2
    delete_parameters = []
    for call in mock_client.execute_query.call_args_list:
        query = call.args[0]
        assert "team_id = %(team_id)s AND session_id IN %(session_ids)s" in query
        assert "is_deleted" not in query
        delete_parameters.append(call.kwargs["query_parameters"])
    assert {"team_id": 1, "session_ids": ["s1", "s2"]} in delete_parameters
    assert {"team_id": 2, "session_ids": ["s3"]} in delete_parameters

    assert result.completed_at >= result.started_at


@pytest.mark.asyncio
async def test_purge_deleted_metadata_issues_no_delete_without_markers():
    mock_client = _mock_clickhouse_client([])

    with patch("posthog.temporal.session_replay.delete_recordings.activities.get_client", return_value=mock_client):
        await purge_deleted_metadata(PurgeDeletedMetadataInput(grace_period_days=10))

    mock_client.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_purge_deleted_metadata_batches_deletes_per_team():
    marker_rows = [{"team_id": "1", "session_id": f"s{i}"} for i in range(PURGE_DELETE_BATCH_SIZE + 1)]
    mock_client = _mock_clickhouse_client(marker_rows)

    with patch("posthog.temporal.session_replay.delete_recordings.activities.get_client", return_value=mock_client):
        await purge_deleted_metadata(PurgeDeletedMetadataInput(grace_period_days=10))

    assert mock_client.execute_query.call_count == 2
    batch_sizes = [
        len(call.kwargs["query_parameters"]["session_ids"]) for call in mock_client.execute_query.call_args_list
    ]
    assert batch_sizes == [PURGE_DELETE_BATCH_SIZE, 1]


@pytest.mark.asyncio
async def test_delete_team_metadata_deletes_by_team_id():
    mock_client = _mock_clickhouse_client([])

    with patch("posthog.temporal.session_replay.delete_recordings.activities.get_client", return_value=mock_client):
        await delete_team_metadata(DeleteTeamMetadataInput(team_id=123))

    mock_client.execute_query.assert_called_once()
    query = mock_client.execute_query.call_args.args[0]
    assert "DELETE FROM sharded_session_replay_events" in query
    assert "team_id = %(team_id)s" in query
    assert mock_client.execute_query.call_args.kwargs["query_parameters"] == {"team_id": 123}


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
