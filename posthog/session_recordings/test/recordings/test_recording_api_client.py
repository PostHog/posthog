import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from posthog.session_recordings.recordings.errors import BlockFetchError, RecordingDeletedError
from posthog.session_recordings.recordings.recording_api_client import RecordingApiClient, recording_api_client


class TestRecordingApiClient:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return RecordingApiClient(mock_session, "http://localhost:6740")

    @pytest.fixture
    def client_with_trailing_slash(self, mock_session):
        return RecordingApiClient(mock_session, "http://localhost:6740/")

    def test_init_strips_trailing_slash(self, client_with_trailing_slash):
        assert client_with_trailing_slash.base_url == "http://localhost:6740"


class TestFetchBlock:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return RecordingApiClient(mock_session, "http://localhost:6740")

    @pytest.mark.asyncio
    async def test_returns_compressed_bytes_by_default(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"compressed-data")
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.fetch_block(
            "key",
            0,
            100,
            "session-123",
            1,
        )

        assert result == b"compressed-data"
        mock_session.get.assert_called_once_with(
            "http://localhost:6740/api/projects/1/recordings/session-123/block",
            params={"key": "key", "start_byte": 0, "end_byte": 100},
        )

    @pytest.mark.asyncio
    async def test_decompress_passes_param(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b'{"type": 3, "data": {}}')
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.fetch_block(
            "key",
            0,
            100,
            "session-123",
            1,
            decompress=True,
        )

        assert result == b'{"type": 3, "data": {}}'
        mock_session.get.assert_called_once_with(
            "http://localhost:6740/api/projects/1/recordings/session-123/block",
            params={"key": "key", "start_byte": 0, "end_byte": 100, "decompress": "true"},
        )

    @pytest.mark.asyncio
    async def test_404_raises_error(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(BlockFetchError, match="Block not found"):
            await client.fetch_block(
                "key",
                0,
                100,
                "session-123",
                1,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("deleted_at", [1700000000, None])
    async def test_410_raises_recording_deleted_error(self, client, mock_session, deleted_at):
        mock_response = AsyncMock()
        mock_response.status = 410
        mock_response.json = AsyncMock(return_value={"error": "Recording has been deleted", "deleted_at": deleted_at})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(RecordingDeletedError, match="Recording has been deleted") as exc_info:
            await client.fetch_block(
                "key",
                0,
                100,
                "session-123",
                1,
            )
        assert exc_info.value.deleted_at == deleted_at

    @pytest.mark.asyncio
    async def test_client_error_raises_error(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=500,
            )
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(BlockFetchError, match="Failed to fetch block from Recording API"):
            await client.fetch_block(
                "key",
                0,
                100,
                "session-123",
                1,
            )


class TestListBlocks:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return RecordingApiClient(mock_session, "http://localhost:6740")

    @pytest.mark.asyncio
    async def test_returns_blocks(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value={
                "blocks": [
                    {
                        "key": "path/key1",
                        "start_byte": 0,
                        "end_byte": 100,
                        "start_timestamp": "2024-01-01T00:00:00Z",
                        "end_timestamp": "2024-01-01T00:01:00Z",
                    }
                ]
            }
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.list_blocks("session-123", 1)

        assert result == [
            {
                "key": "path/key1",
                "start_byte": 0,
                "end_byte": 100,
                "start_timestamp": "2024-01-01T00:00:00Z",
                "end_timestamp": "2024-01-01T00:01:00Z",
            }
        ]
        mock_session.get.assert_called_once_with(
            "http://localhost:6740/api/projects/1/recordings/session-123/blocks",
        )

    @pytest.mark.asyncio
    async def test_404_returns_empty_list(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.list_blocks("session-123", 1)

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_blocks_response(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value={"blocks": []})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.list_blocks("session-123", 1)

        assert result == []

    @pytest.mark.asyncio
    async def test_server_error_raises(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=500,
            )
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(aiohttp.ClientResponseError):
            await client.list_blocks("session-123", 1)


class TestDeleteRecordings:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return RecordingApiClient(mock_session, "http://localhost:6740")

    @pytest.mark.asyncio
    async def test_successful_delete(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value=[
                {"sessionId": "s1", "ok": True, "status": "deleted", "deletedAt": 1700000000},
                {"sessionId": "s2", "ok": True, "status": "deleted", "deletedAt": 1700000000},
            ]
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.post = MagicMock(return_value=mock_response)

        result = await client.delete_recordings(["s1", "s2"], 1, deleted_by="test@posthog.com")

        assert result == []
        mock_session.post.assert_called_once_with(
            "http://localhost:6740/api/projects/1/recordings/delete",
            json={"session_ids": ["s1", "s2"], "deleted_by": "test@posthog.com"},
        )

    @pytest.mark.asyncio
    async def test_partial_failure(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value=[
                {"sessionId": "s1", "ok": True, "status": "deleted", "deletedAt": 1700000000},
                {"sessionId": "s2", "ok": False, "error": "shred_failed"},
            ]
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.post = MagicMock(return_value=mock_response)

        result = await client.delete_recordings(["s1", "s2"], 1, deleted_by="test@posthog.com")

        assert result == ["s2"]

    @pytest.mark.asyncio
    async def test_http_error_returns_all_as_failed(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=500,
            )
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.post = MagicMock(return_value=mock_response)

        result = await client.delete_recordings(["s1", "s2"], 1, deleted_by="test@posthog.com")

        assert result == ["s1", "s2"]


class TestRecordingApiClientContextManager:
    @pytest.mark.asyncio
    async def test_raises_error_when_url_not_configured(self):
        with patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = None

            with pytest.raises(RuntimeError, match="RECORDING_API_URL is not configured"):
                async with recording_api_client():
                    pass

    @pytest.mark.asyncio
    async def test_raises_error_when_url_is_empty_string(self):
        with patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = ""

            with pytest.raises(RuntimeError, match="RECORDING_API_URL is not configured"):
                async with recording_api_client():
                    pass

    @pytest.mark.asyncio
    async def test_creates_client_with_configured_url(self):
        with patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = "http://test-api:8080"
            mock_settings.INTERNAL_API_SECRET = ""
            mock_settings.DEBUG = True
            mock_settings.RECORDING_API_PROBE_ON_OPEN = False

            with patch(
                "posthog.session_recordings.recordings.recording_api_client.aiohttp.ClientSession"
            ) as mock_client_session:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_client_session.return_value = mock_session

                async with recording_api_client() as client:
                    assert client.base_url == "http://test-api:8080"
                    assert client.session == mock_session

                mock_client_session.assert_called_once()
                call_kwargs = mock_client_session.call_args[1]
                assert call_kwargs["timeout"].total == 30
                assert call_kwargs["timeout"].connect == 5
                assert call_kwargs["headers"] == {}

    @pytest.mark.asyncio
    async def test_warns_when_secret_missing_in_production(self):
        with (
            patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings,
            patch("posthog.session_recordings.recordings.recording_api_client.logger") as mock_logger,
            patch(
                "posthog.session_recordings.recordings.recording_api_client.aiohttp.ClientSession"
            ) as mock_client_session,
        ):
            mock_settings.RECORDING_API_URL = "http://test-api:8080"
            mock_settings.INTERNAL_API_SECRET = ""
            mock_settings.DEBUG = False
            mock_settings.RECORDING_API_PROBE_ON_OPEN = False

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_client_session.return_value = mock_session

            async with recording_api_client():
                pass

            mock_logger.warning.assert_called_once_with("recording_api_client.missing_internal_api_secret")

    @pytest.mark.asyncio
    async def test_passes_internal_api_secret_header(self):
        with patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = "http://test-api:8080"
            mock_settings.INTERNAL_API_SECRET = "test-secret"
            mock_settings.RECORDING_API_PROBE_ON_OPEN = False

            with patch(
                "posthog.session_recordings.recordings.recording_api_client.aiohttp.ClientSession"
            ) as mock_client_session:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_client_session.return_value = mock_session

                async with recording_api_client() as client:
                    assert client.session == mock_session

                call_kwargs = mock_client_session.call_args[1]
                assert call_kwargs["headers"] == {"X-Internal-Api-Secret": "test-secret"}


def _make_probe_response(*, status: int, content_type: str) -> AsyncMock:
    """Build a context-manager-shaped aiohttp response mock for probe assertions."""
    resp = AsyncMock()
    resp.status = status
    resp.headers = {"content-type": content_type}
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


def _make_session_yielding(response_mock: AsyncMock) -> AsyncMock:
    """Build a session mock whose get() returns the configured response."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    session.get = MagicMock(return_value=response_mock)
    session.close = AsyncMock(return_value=None)
    return session


class TestProbeOnOpen:
    """The probe loop sidesteps an ultimate-express route-miss bug on cold TCP
    connections. See module docstring on `recording_api_client.py`."""

    @pytest.mark.asyncio
    async def test_returns_session_on_first_json_response(self):
        good = _make_probe_response(status=200, content_type="application/json; charset=utf-8")
        session = _make_session_yielding(good)

        with patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = "http://test-api:8080"
            mock_settings.INTERNAL_API_SECRET = ""
            mock_settings.DEBUG = True
            mock_settings.RECORDING_API_PROBE_ON_OPEN = True

            with patch(
                "posthog.session_recordings.recordings.recording_api_client.aiohttp.ClientSession",
                return_value=session,
            ) as mock_client_session:
                async with recording_api_client() as client:
                    assert client.session is session

                mock_client_session.assert_called_once()
                session.get.assert_called_once()
                probe_url = session.get.call_args[0][0]
                # Probes hit a router-mounted path so they can detect the bug.
                assert "/api/projects/" in probe_url
                assert "/recordings/" in probe_url
                assert probe_url.endswith("/blocks")

    @pytest.mark.asyncio
    async def test_retries_when_first_response_is_html(self):
        bad = _make_probe_response(status=404, content_type="text/html; charset=utf-8")
        good = _make_probe_response(status=200, content_type="application/json; charset=utf-8")

        bad_session = _make_session_yielding(bad)
        good_session = _make_session_yielding(good)

        with patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = "http://test-api:8080"
            mock_settings.INTERNAL_API_SECRET = ""
            mock_settings.DEBUG = True
            mock_settings.RECORDING_API_PROBE_ON_OPEN = True

            with patch(
                "posthog.session_recordings.recordings.recording_api_client.aiohttp.ClientSession",
                side_effect=[bad_session, good_session],
            ):
                async with recording_api_client() as client:
                    assert client.session is good_session

                bad_session.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_after_max_probes(self):
        bad = _make_probe_response(status=404, content_type="text/html; charset=utf-8")
        sessions = [_make_session_yielding(bad) for _ in range(6)]

        with (
            patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings,
            patch("posthog.session_recordings.recordings.recording_api_client.logger") as mock_logger,
            patch(
                "posthog.session_recordings.recordings.recording_api_client.aiohttp.ClientSession",
                side_effect=sessions,
            ),
        ):
            mock_settings.RECORDING_API_URL = "http://test-api:8080"
            mock_settings.INTERNAL_API_SECRET = ""
            mock_settings.DEBUG = True
            mock_settings.RECORDING_API_PROBE_ON_OPEN = True

            async with recording_api_client() as client:
                # Last session is yielded — caller still gets a usable client.
                assert client.session is sessions[-1]

            mock_logger.warning.assert_any_call(
                "recording_api_client.probe_exhausted",
                attempts=6,
                hint=(
                    "recording-api is returning HTML for router-mounted routes — "
                    "this usually points at the ultimate-express route-miss bug (see module docstring)"
                ),
            )
            # Every poisoned session except the last must be explicitly closed.
            for poisoned in sessions[:-1]:
                poisoned.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_disabled_skips_probe(self):
        with patch("posthog.session_recordings.recordings.recording_api_client.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = "http://test-api:8080"
            mock_settings.INTERNAL_API_SECRET = ""
            mock_settings.DEBUG = True
            mock_settings.RECORDING_API_PROBE_ON_OPEN = False

            with patch(
                "posthog.session_recordings.recordings.recording_api_client.aiohttp.ClientSession"
            ) as mock_client_session:
                session = AsyncMock()
                session.close = AsyncMock(return_value=None)
                mock_client_session.return_value = session

                async with recording_api_client():
                    pass

                # No probe → exactly one session created, get() never called.
                mock_client_session.assert_called_once()
                session.get.assert_not_called()
