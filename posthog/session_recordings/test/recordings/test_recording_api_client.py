import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from posthog.session_recordings.recordings.errors import (
    BlockFetchClientError,
    BlockNotFoundError,
    RecordingDeletedError,
    TransientBlockFetchError,
)
from posthog.session_recordings.recordings.recording_api_client import (
    _MAX_INLINE_RETRY_AFTER_SECONDS,
    BLOCK_FETCH_RETRY_COUNTER,
    RecordingApiClient,
    _parse_retry_after,
    recording_api_client,
)


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

    @pytest.fixture(autouse=True)
    def _no_real_retry_sleep(self):
        # tenacity's wait_random_exponential sleeps between retries via asyncio.sleep;
        # stub it so the retry-exercising tests don't block in real time.
        with patch("asyncio.sleep", new_callable=AsyncMock):
            yield

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
    async def test_404_raises_block_not_found(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        # A genuinely-missing block is a terminal BlockNotFoundError, not a transient BlockFetchError.
        with pytest.raises(BlockNotFoundError, match="Block not found"):
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

        with pytest.raises(TransientBlockFetchError, match="Failed to fetch block from Recording API"):
            await client.fetch_block(
                "key",
                0,
                100,
                "session-123",
                1,
            )

        # 5xx is transient, so it should be retried up to the attempt limit before giving up.
        assert mock_session.get.call_count == 3

    @staticmethod
    def _response_mock(
        status: int,
        *,
        body: bytes | None = None,
        raise_status: int | None = None,
        headers: dict[str, str] | None = None,
    ):
        mock_response = AsyncMock()
        mock_response.status = status
        mock_response.read = AsyncMock(return_value=body)
        if raise_status is not None:
            mock_response.raise_for_status = MagicMock(
                side_effect=aiohttp.ClientResponseError(
                    request_info=MagicMock(), history=(), status=raise_status, headers=headers
                )
            )
        else:
            mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        return mock_response

    @pytest.mark.asyncio
    async def test_retries_transient_error_then_succeeds(self, client, mock_session):
        mock_session.get = MagicMock(
            side_effect=[
                self._response_mock(200, raise_status=503),
                self._response_mock(200, body=b"recovered-data"),
            ]
        )

        result = await client.fetch_block("key", 0, 100, "session-123", 1)

        assert result == b"recovered-data"
        assert mock_session.get.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 401, 403, 422])
    async def test_non_retriable_4xx_returned_as_is_not_retried(self, client, mock_session, status_code):
        mock_session.get = MagicMock(return_value=self._response_mock(200, raise_status=status_code))

        # A genuine client error is returned to the client as its own status, not masked as a 503.
        with pytest.raises(BlockFetchClientError) as exc_info:
            await client.fetch_block("key", 0, 100, "session-123", 1)

        assert exc_info.value.status_code == status_code
        assert exc_info.value.retry_after is None
        # Fail fast without retrying — retrying a client error won't help.
        assert mock_session.get.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [408, 429])
    async def test_retries_back_off_4xx_then_succeeds(self, client, mock_session, status_code):
        mock_session.get = MagicMock(
            side_effect=[
                self._response_mock(200, raise_status=status_code),
                self._response_mock(200, body=b"recovered-data"),
            ]
        )

        # 408/429 ask us to back off rather than signalling a permanent client error, so retry.
        result = await client.fetch_block("key", 0, 100, "session-123", 1)

        assert result == b"recovered-data"
        assert mock_session.get.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [429, 503])
    async def test_honors_retry_after_header(self, client, mock_session, status_code):
        mock_session.get = MagicMock(
            side_effect=[
                self._response_mock(200, raise_status=status_code, headers={"Retry-After": "2"}),
                self._response_mock(200, body=b"recovered-data"),
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            result = await client.fetch_block("key", 0, 100, "session-123", 1)

        assert result == b"recovered-data"
        # The server told us when to come back, so the backoff honors it instead of guessing.
        sleep_mock.assert_awaited_once_with(2.0)

    @pytest.mark.asyncio
    async def test_clamps_large_retry_after_for_retried_status(self, client, mock_session):
        # A 503 stays retriable; its (large) Retry-After is clamped to the inline budget so it
        # can't pin the request handler.
        mock_session.get = MagicMock(
            side_effect=[
                self._response_mock(200, raise_status=503, headers={"Retry-After": "3600"}),
                self._response_mock(200, body=b"recovered-data"),
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await client.fetch_block("key", 0, 100, "session-123", 1)

        sleep_mock.assert_awaited_once_with(_MAX_INLINE_RETRY_AFTER_SECONDS)

    @pytest.mark.asyncio
    async def test_429_with_long_retry_after_is_handed_back_not_retried(self, client, mock_session):
        # A 429 asking for longer than the inline budget must not be retried in-process; it becomes
        # a BlockFetchClientError carrying the status + Retry-After for the client to obey.
        mock_session.get = MagicMock(
            return_value=self._response_mock(200, raise_status=429, headers={"Retry-After": "60"})
        )

        with pytest.raises(BlockFetchClientError) as exc_info:
            await client.fetch_block("key", 0, 100, "session-123", 1)

        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == "60"
        # Not retried — we handed the back-off to the client instead of sleeping a worker.
        assert mock_session.get.call_count == 1

    @pytest.mark.asyncio
    async def test_clamps_negative_retry_after_to_zero(self, client, mock_session):
        # An HTTP-date Retry-After in the past parses to a negative delay; the wait must floor it
        # to 0 rather than passing a negative sleep through.
        mock_session.get = MagicMock(
            side_effect=[
                self._response_mock(200, raise_status=503, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
                self._response_mock(200, body=b"recovered-data"),
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await client.fetch_block("key", 0, 100, "session-123", 1)

        sleep_mock.assert_awaited_once_with(0.0)

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2", 2.0),
            ("0", 0.0),
            ("", None),
            ("   ", None),
            ("soon", None),
        ],
    )
    def test_parse_retry_after(self, value, expected):
        assert _parse_retry_after(value) == expected

    def test_parse_retry_after_http_date(self):
        # A past HTTP-date is negative seconds-from-now; a far-future one is positive. Locks the
        # date branch and its tz-naive handling without depending on the exact current time.
        past = _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT")
        future = _parse_retry_after("Mon, 01 Jan 2099 00:00:00 GMT")
        assert past is not None and past < 0
        assert future is not None and future > 0

    @pytest.mark.asyncio
    async def test_counts_retry_attempt_and_recovery(self, client, mock_session):
        attempts_before = BLOCK_FETCH_RETRY_COUNTER.labels(outcome="attempt")._value.get()
        recovered_before = BLOCK_FETCH_RETRY_COUNTER.labels(outcome="recovered")._value.get()

        mock_session.get = MagicMock(
            side_effect=[
                self._response_mock(200, raise_status=503),
                self._response_mock(200, body=b"recovered-data"),
            ]
        )

        await client.fetch_block("key", 0, 100, "session-123", 1)

        # One retry happened, and that retry recovered the fetch — both must be counted.
        assert BLOCK_FETCH_RETRY_COUNTER.labels(outcome="attempt")._value.get() == attempts_before + 1
        assert BLOCK_FETCH_RETRY_COUNTER.labels(outcome="recovered")._value.get() == recovered_before + 1

    @pytest.mark.asyncio
    async def test_does_not_count_recovery_on_first_try_success(self, client, mock_session):
        recovered_before = BLOCK_FETCH_RETRY_COUNTER.labels(outcome="recovered")._value.get()

        mock_session.get = MagicMock(return_value=self._response_mock(200, body=b"data"))

        await client.fetch_block("key", 0, 100, "session-123", 1)

        # No retry was needed, so nothing recovered.
        assert BLOCK_FETCH_RETRY_COUNTER.labels(outcome="recovered")._value.get() == recovered_before

    @pytest.mark.asyncio
    async def test_does_not_retry_404(self, client, mock_session):
        mock_session.get = MagicMock(return_value=self._response_mock(404))

        with pytest.raises(BlockNotFoundError, match="Block not found"):
            await client.fetch_block("key", 0, 100, "session-123", 1)

        # A genuinely-missing block is terminal — fail fast without retrying.
        assert mock_session.get.call_count == 1


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
